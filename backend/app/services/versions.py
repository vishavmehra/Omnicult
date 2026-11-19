"""Creative Studio persistence: the version tree, operations, locks and diffs.

Authorization is the rest of the API's: a campaign belongs to a project in a workspace, the caller reaches it through
workspace membership (a stranger gets 404), and viewers and reviewers cannot write (403). Every node, operation, lock
and chip carries the project and campaign ids, so nothing here can cross a campaign.

The operation engine (app.studio.engine) is pure; `record_operation` is the one place that runs it against stored
state, so a hand edit, a Tweak Chip, a transcreation and a restore all create nodes the same way and all respect locks.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import versions as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.campaigns import current_version
from app.services.claims import LIVE_STATUSES
from app.services.common import conflict, get_owned, not_found, paginate, require_writable, touch
from app.studio import engine
from app.studio.engine import Edit, OperationRejected, OpSpec, Snapshot

DEFAULT_LABELS = {
    "manual_edit": "Manual edit", "replace_text": "Text replaced", "transcreate": "Transcreation", "apply_chip": "Tweak chip",
    "swap_reference": "Reference swapped", "change_setting": "Setting changed", "tone_shift": "Tone shifted", "restore": "Restored", "remake": "Remake",
}


# --- views ----------------------------------------------------------------------------------


def to_summary(node: m.VersionNode) -> v.VersionSummary:
    return v.VersionSummary(
        id=node.id, campaign_id=node.campaign_id, parent_id=node.parent_id, label=node.label, created_by=node.created_by,
        actor=node.actor, region_code=node.region_code, language=node.language,  # type: ignore[arg-type]
        settings=v.VersionSettings.model_validate(node.settings or {}), operation_id=node.operation_id,
        element_count=len(node.elements), created_at=node.created_at,
    )


def to_node(node: m.VersionNode) -> v.VersionNode:
    return v.VersionNode(**to_summary(node).model_dump(), elements=[v.CreativeElement.model_validate(e) for e in node.elements])


def to_operation(op: m.Operation) -> v.Operation:
    return v.Operation(
        id=op.id, campaign_id=op.campaign_id, kind=op.kind, source_version_id=op.source_version_id,  # type: ignore[arg-type]
        result_version_id=op.result_version_id, target_element_ids=op.target_element_ids, params=op.params, reason=op.reason,
        claim_ids=op.claim_ids, actor=op.actor, actor_user_id=op.actor_user_id,  # type: ignore[arg-type]
        prompt_version=op.prompt_version, estimated_cost_usd=op.estimated_cost_usd,
        status=op.status, rejection=v.Rejection.model_validate(op.rejection) if op.rejection else None,  # type: ignore[arg-type]
        created_at=op.created_at,
    )


def to_lock(lock: m.Lock) -> v.Lock:
    return v.Lock(
        id=lock.id, campaign_id=lock.campaign_id, element_id=lock.element_id, locked_by=lock.locked_by, reason=lock.reason,
        locked_at=lock.locked_at, released_at=lock.released_at, released_by=lock.released_by,
    )


def snapshot_of(node: m.VersionNode) -> Snapshot:
    return Snapshot(
        [dict(e) for e in node.elements], node.region_code, node.language,
        {"tone": (node.settings or {}).get("tone"), "generation": (node.settings or {}).get("generation")},
    )


# --- lookups ----------------------------------------------------------------------------------


async def campaign_for(
    s: AsyncSession, user_id: UUID, campaign_id: UUID, *, writable: bool = False
) -> tuple[m.Campaign, m.Project]:
    """The campaign and its project, 404 when the caller cannot reach its workspace, 403/409 when a write is not allowed."""
    campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    if writable:
        require_writable(project)
    return campaign, project


async def node_in(s: AsyncSession, campaign: m.Campaign, node_id: UUID, field: str | None = None) -> m.VersionNode:
    node = await s.get(m.VersionNode, node_id)
    if node is None or node.campaign_id != campaign.id:
        raise not_found("Version", field)
    return node


async def newest_node(s: AsyncSession, campaign_id: UUID) -> m.VersionNode | None:
    stmt = select(m.VersionNode).where(m.VersionNode.campaign_id == campaign_id)
    return (await s.execute(stmt.order_by(m.VersionNode.created_at.desc(), m.VersionNode.id.desc()).limit(1))).scalar_one_or_none()


async def active_locks(s: AsyncSession, campaign_id: UUID) -> set[str]:
    stmt = select(m.Lock.element_id).where(m.Lock.campaign_id == campaign_id, m.Lock.released_at.is_(None))
    return set((await s.execute(stmt)).scalars())


async def verified_claim_ids(s: AsyncSession, project: m.Project, claim_ids: list[UUID], field: str = "claim_ids") -> list[UUID]:
    """Claim ids that exist and are visible to the project's workspace in its mode; anything else is a 422."""
    ids = list(dict.fromkeys(claim_ids))
    if not ids:
        return []
    stmt = select(m.Claim.id).where(
        m.Claim.id.in_(ids), m.Claim.mode == project.mode, m.Claim.status.in_(LIVE_STATUSES),
        (m.Claim.workspace_id == project.workspace_id) | m.Claim.workspace_id.is_(None),
    )
    found = set((await s.execute(stmt)).scalars())
    for index, claim_id in enumerate(ids):
        if claim_id not in found:
            message = f"Claim {claim_id} does not exist in this workspace."
            raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=f"{field}.{index}", message=message)])
    return ids


# --- the one place operations run -----------------------------------------------------------------


def _requested_ids(spec: OpSpec) -> list[str]:
    return [e.element_id for e in spec.edits] + ([spec.swap[0]] if spec.swap else [])


async def record_operation(
    s: AsyncSession, *, project: m.Project, campaign: m.Campaign, source: m.VersionNode, spec: OpSpec, actor: str,
    actor_user_id: UUID | None, reason: str, claim_ids: list[UUID], params: Mapping[str, Any], label: str | None = None,
    prompt_version: str | None = None, estimated_cost_usd: float | None = None, rejection: v.Rejection | None = None,
) -> tuple[m.Operation, m.VersionNode | None]:
    """Run `spec` on `source` through the engine. An applied operation creates a new node (the source is never changed);
    a refused one (a locked element, an invalid edit, or `rejection` passed by a caller whose checks failed) is stored as
    a rejected operation and returns no node. The caller decides what to tell the user."""
    now, op_id = utcnow(), uuid4()
    locks = await active_locks(s, campaign.id)
    node: m.VersionNode | None = None
    applied: engine.Applied | None = None
    if rejection is None:
        try:
            applied = engine.apply_operation(snapshot_of(source), spec, locks)
        except OperationRejected as refused:
            rejection = v.Rejection(code=refused.code, message=refused.message, element_ids=refused.element_ids)  # type: ignore[arg-type]
    targets = applied.target_ids if applied else (rejection.element_ids if rejection and rejection.element_ids else _requested_ids(spec))
    if applied is not None:
        snap = applied.snapshot
        for element in snap.elements:
            element["locked"] = element["id"] in locks  # a node records the locks in force when it was made
        node = m.VersionNode(
            id=uuid4(), campaign_id=campaign.id, project_id=project.id, parent_id=source.id,
            label=label or DEFAULT_LABELS[spec.kind], created_by=actor_user_id, actor=actor, region_code=snap.region_code,
            language=snap.language, settings={"tone": snap.settings.get("tone"), "generation": snap.settings.get("generation")},
            elements=snap.elements, operation_id=op_id, created_at=now,
        )
    op = m.Operation(
        id=op_id, campaign_id=campaign.id, project_id=project.id, source_version_id=source.id,
        result_version_id=node.id if node else None, kind=spec.kind, target_element_ids=targets, params=dict(params),
        reason=reason, claim_ids=[str(c) for c in claim_ids], actor=actor, actor_user_id=actor_user_id,
        prompt_version=prompt_version, estimated_cost_usd=estimated_cost_usd,
        status="applied" if node else "rejected", rejection=rejection.model_dump(mode="json") if rejection else None,
        created_at=now,
    )
    if node is not None:
        s.add(node)
        await s.flush()  # the node row first: the operation references it
    s.add(op)
    await s.flush()
    await record_audit(
        s, action="studio.operation", target_type="operation", target_id=str(op.id), workspace_id=project.workspace_id,
        actor_user_id=actor_user_id, detail={"kind": spec.kind, "status": op.status, "actor": actor, "source_version_id": str(source.id)},
    )
    touch(project)
    return op, node


def raise_if_rejected(op: m.Operation) -> None:
    """Turn a stored rejection into the API error (the rejected operation is already committed by the caller)."""
    if op.status == "rejected":
        rejection = op.rejection or {}
        details = [ErrorDetail(field="operation", message=f"{rejection.get('code', 'INVALID')}: {e}") for e in rejection.get("element_ids", [])]
        raise Conflict(rejection.get("message", "The operation was refused."), details=details or None)


# --- versions ---------------------------------------------------------------------------------


def _campaign_elements(content: Mapping[str, Any], language: str | None) -> list[v.CreativeElement]:
    """The campaign copy as elements. Language and script come from each line's own letters (Marathi copy is not tagged
    English): Latin is English, any other script takes `language` (the brief's origin language) when that is not English."""
    declared = language if language and language != "en" else None
    out = []
    for eid, kind, field in (("headline", "headline", "headline"), ("body", "body", "body"), ("cta", "cta", "call_to_action")):
        if content.get(field):
            lang, script = _text_language(content[field], declared)
            out.append(v.CreativeElement(id=eid, kind=kind, value=content[field], language=lang, script=script))  # type: ignore[arg-type]
    return out


async def _origin_language(s: AsyncSession, campaign_id: UUID) -> str | None:
    """The first language the brief lists for the region the original was made in."""
    row = await s.scalar(select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
                         .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))
    content = (row.content if row else None) or {}
    origin = (content.get("regions") or {}).get("origin")
    first = next(iter(((content.get("languages") or {}).get(origin) or [])), None) if origin else None
    return first if isinstance(first, str) else None


XRAY_TAGS = {"video": "film", "image": "kv", "audio": "audio"}


def _text_language(text: str, declared: str | None) -> tuple[str | None, str]:
    """(language, script) of a line read from a creative: English for Latin script, else the creative's declared language."""
    from app.media.remake import dominant_script

    script = dominant_script(text)
    return ("en" if script == "Latn" else declared), script


def merge_marks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A logo read as an icon and the brand name beside it becomes ONE logo with the union of both boxes: locked, restored
    and drawn as one mark (Remake: Video draws the Brand Kit lockup once per logo). Marks merge when their boxes share most
    of a row and sit close together."""
    others = [i for i in items if i["role"] != "logo"]
    marks: list[dict[str, Any]] = []
    for item in sorted((i for i in items if i["role"] == "logo"), key=lambda i: i["bbox"][0]):
        x, y, w, h = item["bbox"]
        last = marks[-1]["bbox"] if marks else None
        if last is not None:
            lx, ly, lw, lh = last
            shared = min(ly + lh, y + h) - max(ly, y)
            if shared > 0.5 * min(lh, h) and x - (lx + lw) < 0.05:
                x0, y0 = min(lx, x), min(ly, y)
                marks[-1] = {**marks[-1], "bbox": [round(x0, 4), round(y0, 4), round(max(lx + lw, x + w) - x0, 4), round(max(ly + lh, y + h) - y0, 4)]}
                continue
        marks.append(dict(item))
    return others + marks


def layout_elements(creatives: list[tuple[m.CreativeAsset, list[m.CreativeScene]]]) -> list[v.CreativeElement]:
    """The elements X-Ray found, with their positions: per scene a `scene` element (pictures only), the text, logo and pack
    the vision model located (box from its observation, `bbox_source` model_detected), and the transcript as voice-over lines.
    Every element points at its X-Ray scene, so Remake, Risk Check and Format Fit can place it."""
    out: list[v.CreativeElement] = []
    seen: dict[str, int] = {}
    for creative, scenes in creatives:
        base = XRAY_TAGS.get(creative.kind, "creative")
        seen[base] = seen.get(base, 0) + 1
        tag = base if seen[base] == 1 else f"{base}{seen[base]}"
        frames = {f.get("timestamp_ms"): f for f in (creative.analysis or {}).get("frames", [])}
        line = 0
        for scene in scenes:
            prefix = tag if creative.kind == "image" else f"{tag}-s{scene.position + 1}"
            payload = scene.payload or {}
            if creative.kind != "audio":
                keyframe = scene.keyframe_asset_id or creative.asset_id
                out.append(v.CreativeElement(id=f"{prefix}-scene", kind="scene", value=f"asset:{keyframe}", bbox=[0.0, 0.0, 1.0, 1.0],
                                             scene_id=str(scene.id)))
            used: dict[str, int] = {}
            for item in sorted(merge_marks(payload.get("layout") or []), key=lambda i: (i["bbox"][1], i["bbox"][0])):
                role = item["role"]
                used[role] = used.get(role, 0) + 1
                eid = f"{prefix}-{role}" if used[role] == 1 else f"{prefix}-{role}-{used[role]}"
                if item.get("text"):
                    language, script = _text_language(item["text"], creative.language)
                    value: Any = item["text"]
                else:
                    observed = next((o for o in (frames.get(item["frame_ms"]) or {}).get("observations", [])
                                     if o.get("id") == item.get("observation_id")), None)
                    language, script, value = None, None, (observed or {}).get("description") or role
                out.append(v.CreativeElement(id=eid, kind=role, value=value, language=language, script=script, bbox=item["bbox"],
                                             scene_id=str(scene.id), bbox_source="model_detected"))
            for segment in payload.get("transcript") or []:
                line += 1
                language, script = _text_language(segment["text"], segment.get("language") or creative.language)
                out.append(v.CreativeElement(id=f"{tag}-vo-{line}", kind="voiceover", value=segment["text"], language=language,
                                             script=script, scene_id=str(scene.id)))
    return out[:200]


async def _xray_elements(s: AsyncSession, campaign: m.Campaign) -> tuple[list[v.CreativeElement], str | None, str | None]:
    """The X-Ray layout of every analysed creative of the campaign (newest usable run of each), with the region and language
    the creatives were read for when they agree. 409 when no creative has a usable X-Ray yet."""
    rows = (await s.execute(select(m.CreativeAsset).where(m.CreativeAsset.campaign_id == campaign.id, m.CreativeAsset.current_run_id.is_not(None))
                            .order_by(m.CreativeAsset.created_at, m.CreativeAsset.id))).scalars().all()
    creatives = []
    for row in rows:
        scenes = (await s.execute(select(m.CreativeScene).where(m.CreativeScene.creative_asset_id == row.id, m.CreativeScene.run_id == row.current_run_id)
                                  .order_by(m.CreativeScene.position))).scalars().all()
        creatives.append((row, list(scenes)))
    elements = layout_elements(creatives)
    if not elements:
        raise conflict("from_xray", "No creative of this campaign has an X-Ray result yet. Run Creative X-Ray first.")
    regions, languages = {r.region_code for r in rows}, {r.language for r in rows}
    return elements, (regions.pop() if len(regions) == 1 else None), (languages.pop() if len(languages) == 1 else None)


async def create_version(user_id: UUID, campaign_id: UUID, body: v.VersionCreate) -> v.VersionNode:
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        region_code, language = body.region_code, body.language
        if body.from_xray:
            elements, found_region, found_language = await _xray_elements(s, campaign)
            region_code, language = region_code or found_region, language or found_language
        else:
            elements = body.elements or _campaign_elements((await current_version(s, campaign.id)).content,
                                                           await _origin_language(s, campaign.id) or body.language)
            if language is None and not body.elements:  # the campaign copy's own language, as its lines were tagged
                tagged = [e.language for e in elements if e.language]
                language = max(set(tagged), key=tagged.count) if tagged else None
        locks = await active_locks(s, campaign.id)
        dumped = [{**e.model_dump(mode="json"), "locked": e.id in locks} for e in elements]
        node = m.VersionNode(
            id=uuid4(), campaign_id=campaign.id, project_id=project.id, parent_id=None, label=body.label, created_by=user_id,
            actor="user", region_code=region_code, language=language,
            settings={"tone": body.tone.model_dump() if body.tone else None, "generation": None}, elements=dumped,
            operation_id=None, created_at=utcnow(),
        )
        s.add(node)
        await s.flush()
        await record_audit(s, action="studio.version_created", target_type="version", target_id=str(node.id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"campaign_id": str(campaign.id)})
        touch(project)
    return to_node(node)


async def list_versions(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> v.VersionPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.VersionNode).where(m.VersionNode.campaign_id == campaign.id)
        rows, total = await paginate(s, stmt.order_by(m.VersionNode.created_at, m.VersionNode.id), limit, offset)
    return v.VersionPage(items=[to_summary(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_version(user_id: UUID, campaign_id: UUID, version_id: UUID) -> v.VersionNode:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        return to_node(await node_in(s, campaign, version_id))


async def diff_versions(user_id: UUID, campaign_id: UUID, from_id: UUID, to_id: UUID) -> v.VersionDiff:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        before = await node_in(s, campaign, from_id, "from")
        after = await node_in(s, campaign, to_id, "to")
    added, removed, changed, preserved = engine.diff_elements(before.elements, after.elements)
    return v.VersionDiff(
        from_id=before.id, to_id=after.id, added=[v.CreativeElement.model_validate(e) for e in added],
        removed=[v.CreativeElement.model_validate(e) for e in removed], changed=[v.ElementChange.model_validate(c) for c in changed],
        preserved=preserved, settings_changes=[v.FieldChange.model_validate(c) for c in engine.diff_settings(snapshot_of(before), snapshot_of(after))],
    )


# --- operations ----------------------------------------------------------------------------------


def _spec_of(operation: Any) -> tuple[OpSpec, dict[str, Any]]:
    params = operation.model_dump(mode="json", exclude={"kind"})
    if operation.kind in ("manual_edit", "replace_text"):
        return OpSpec(operation.kind, edits=[Edit(e.element_id, e.set) for e in operation.edits]), params
    if operation.kind == "swap_reference":
        return OpSpec("swap_reference", swap=(operation.element_id, operation.from_text, operation.to_text)), params
    if operation.kind == "change_setting":
        return OpSpec("change_setting", region_code=operation.region_code, language=operation.language), params
    return OpSpec("tone_shift", tone=operation.tone.model_dump()), params


async def apply_operation(user_id: UUID, campaign_id: UUID, body: v.OperationRequest) -> v.OperationResult:
    """A person's operation. Locks apply to everyone: the target of a locked element is refused (409) and recorded."""
    spec, params = _spec_of(body.operation)
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        source = await node_in(s, campaign, body.version_id, "version_id")
        claim_ids = await verified_claim_ids(s, project, body.claim_ids)
        op, node = await record_operation(
            s, project=project, campaign=campaign, source=source, spec=spec, actor="user", actor_user_id=user_id,
            reason=body.reason, claim_ids=claim_ids, params=params, label=body.label,
        )
    raise_if_rejected(op)  # after the commit: a refused operation stays on record
    assert node is not None
    return v.OperationResult(operation=to_operation(op), version=to_node(node))


async def restore_version(user_id: UUID, campaign_id: UUID, version_id: UUID, body: v.RestoreRequest) -> v.OperationResult:
    """A new node that copies an earlier version, continuing from `onto_version_id` (default: the newest node)."""
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        target = await node_in(s, campaign, version_id)
        onto = await node_in(s, campaign, body.onto_version_id, "onto_version_id") if body.onto_version_id else await newest_node(s, campaign.id)
        assert onto is not None  # `target` exists, so the campaign has at least one node
        op, node = await record_operation(
            s, project=project, campaign=campaign, source=onto, spec=OpSpec("restore", restore_to=snapshot_of(target)),
            actor="user", actor_user_id=user_id, reason=body.reason, claim_ids=[],
            params={"restored_version_id": str(target.id)}, label=f"Restored: {target.label}"[:80],
        )
    raise_if_rejected(op)
    assert node is not None
    return v.OperationResult(operation=to_operation(op), version=to_node(node))


async def list_operations(
    user_id: UUID, campaign_id: UUID, limit: int, offset: int, version_id: UUID | None = None, status: str | None = None,
    kind: str | None = None,
) -> v.OperationPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.Operation).where(m.Operation.campaign_id == campaign.id)
        if version_id is not None:
            stmt = stmt.where((m.Operation.source_version_id == version_id) | (m.Operation.result_version_id == version_id))
        if status is not None:
            stmt = stmt.where(m.Operation.status == status)
        if kind is not None:
            stmt = stmt.where(m.Operation.kind == kind)
        rows, total = await paginate(s, stmt.order_by(m.Operation.created_at.desc(), m.Operation.id), limit, offset)
    return v.OperationPage(items=[to_operation(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_operation(user_id: UUID, campaign_id: UUID, operation_id: UUID) -> v.Operation:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        op = await s.get(m.Operation, operation_id)
        if op is None or op.campaign_id != campaign.id:
            raise NotFound("Operation was not found.")
        return to_operation(op)


# --- locks ---------------------------------------------------------------------------------------


async def _element_exists(s: AsyncSession, campaign_id: UUID, element_id: str) -> bool:
    # ponytail: scans every node's elements in Python; an indexed element table if trees ever reach thousands of nodes.
    rows = (await s.execute(select(m.VersionNode.elements).where(m.VersionNode.campaign_id == campaign_id))).scalars()
    return any(e["id"] == element_id for elements in rows for e in elements)


async def set_lock(user_id: UUID, campaign_id: UUID, element_id: str, body: v.LockCreate) -> v.Lock:
    """Lock an element of the campaign (every version). Idempotent: an element already locked returns its lock."""
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        if not await _element_exists(s, campaign.id, element_id):
            raise conflict("element_id", f"No version of this campaign has an element '{element_id}'.")
        stmt = select(m.Lock).where(m.Lock.campaign_id == campaign.id, m.Lock.element_id == element_id, m.Lock.released_at.is_(None))
        lock = (await s.execute(stmt)).scalar_one_or_none()
        if lock is None:
            lock = m.Lock(id=uuid4(), campaign_id=campaign.id, project_id=project.id, element_id=element_id, locked_by=user_id,
                          reason=body.reason, locked_at=utcnow())
            try:
                async with s.begin_nested():
                    s.add(lock)
                    await s.flush()
            except IntegrityError:  # a concurrent request locked it first; theirs stands
                lock = (await s.execute(stmt)).scalar_one()
            else:
                await record_audit(s, action="studio.lock_set", target_type="lock", target_id=str(lock.id),
                                   workspace_id=project.workspace_id, actor_user_id=user_id,
                                   detail={"campaign_id": str(campaign.id), "element_id": element_id})
                touch(project)
        return to_lock(lock)


async def unset_lock(user_id: UUID, campaign_id: UUID, element_id: str) -> v.Lock:
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        stmt = select(m.Lock).where(m.Lock.campaign_id == campaign.id, m.Lock.element_id == element_id, m.Lock.released_at.is_(None))
        lock = (await s.execute(stmt)).scalar_one_or_none()
        if lock is None:
            raise not_found("Active lock", "element_id")
        lock.released_at, lock.released_by = utcnow(), user_id
        await record_audit(s, action="studio.lock_released", target_type="lock", target_id=str(lock.id),
                           workspace_id=project.workspace_id, actor_user_id=user_id,
                           detail={"campaign_id": str(campaign.id), "element_id": element_id})
        touch(project)
        return to_lock(lock)


async def list_locks(user_id: UUID, campaign_id: UUID, limit: int, offset: int, include_released: bool = False) -> v.LockPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.Lock).where(m.Lock.campaign_id == campaign.id)
        if not include_released:
            stmt = stmt.where(m.Lock.released_at.is_(None))
        rows, total = await paginate(s, stmt.order_by(m.Lock.locked_at, m.Lock.id), limit, offset)
    return v.LockPage(items=[to_lock(r) for r in rows], limit=limit, offset=offset, total=total)
