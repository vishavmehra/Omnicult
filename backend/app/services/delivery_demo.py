"""Demo hook for the Launch Room delivery features: `seed_launch_delivery(user_id, campaign_id)`.

Called by the demo journey after the readiness verdicts exist (`services/demo_journey.py`). On the fictional Aamod project it
makes the three delivery tabs show a real, populated state without any provider call:

1. confirms the rights of the fictional brand's own files (its creatives and the Brand Kit images), the step a person takes
   when uploading with the rights box ticked, so the Asset Pack has files to include;
2. records a person's approval (the demo owner's) for every version whose newest verdict is Go, through the real
   `launch.record_approval`, so those regions have an approved version to pack and plan;
3. creates one review link for the regional versions of Tamil Nadu and Kerala with two sample stakeholder responses, through the
   real review code. The link's secret is discarded: the sample link is shown as an already sent link.

Idempotent: a second call adds nothing. Refuses a project that is not a demo project.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.errors import Conflict
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures import demo_delivery as fx
from app.schemas import delivery as d
from app.schemas import desk as desk_schema
from app.schemas import launch as ls
from app.services import launch, review_links
from app.services.audit import record_audit
from app.services.common import get_owned

LINK_REGIONS = ("IN-TN", "IN-KL")


async def _confirm_rights(user_id: UUID, campaign_id: UUID) -> int:
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        if project.mode != "demo":
            raise Conflict("The delivery demo seed only runs on a demo project.")
        ids = set((await s.execute(select(m.CreativeAsset.asset_id).where(m.CreativeAsset.campaign_id == campaign.id))).scalars())
        design = await s.scalar(select(m.BrandKitDesignRow).where(m.BrandKitDesignRow.project_id == project.id))
        if design is not None:
            kit = desk_schema.KitDesign.model_validate(design.design)
            ids |= {x.asset_id for x in [*kit.logo.lockups, *kit.product_images] if x.asset_id}
        assets = (await s.execute(select(m.Asset).where(m.Asset.project_id == project.id, m.Asset.id.in_(ids), m.Asset.rights_confirmed.is_(False)))).scalars().all() if ids else []
        now = utcnow()
        for asset in assets:
            asset.rights_confirmed, asset.rights_confirmed_at = True, now
        if assets:
            await record_audit(
                s, action="delivery.demo_rights_confirmed", target_type="campaign", target_id=str(campaign.id), workspace_id=project.workspace_id,
                actor_user_id=user_id, detail={"assets": len(assets), "fixture": "aamod"},
            )
        return len(assets)


async def seed_launch_delivery(user_id: UUID, campaign_id: UUID) -> dict[str, int]:
    done = {"rights_confirmed": await _confirm_rights(user_id, campaign_id), "approvals": 0, "review_links": 0, "review_responses": 0}
    board = await launch.readiness_board(user_id, campaign_id)
    for region in board.regions:
        for entry in region.versions:
            if entry.verdict.verdict == "go" and entry.latest_approval is None:
                await launch.record_approval(user_id, campaign_id, ls.ApprovalCreate(
                    region_code=region.region_code, version_id=entry.verdict.version_id, decision="approve", reason=fx.APPROVAL_REASON,
                    readiness_verdict_id=entry.verdict.id))
                done["approvals"] += 1
    async with read_session() as s:
        have = await s.scalar(select(m.ReviewLink.id).where(m.ReviewLink.campaign_id == campaign_id, m.ReviewLink.label == fx.LINK_LABEL))
    if have is not None:
        return done
    newest = {r.region_code: max(r.versions, key=lambda v: v.verdict.computed_at).verdict.version_id for r in board.regions if r.versions}
    items = [d.ReviewItem(version_id=newest[code], region_code=code) for code in LINK_REGIONS if code in newest]
    if not items:
        return done
    link = await review_links.create_link(user_id, campaign_id, d.ReviewLinkCreate(label=fx.LINK_LABEL, note=fx.LINK_NOTE, items=items, expires_in_days=30))
    done["review_links"] = 1
    digest = review_links.hash_secret(link.token)
    for code, decision, name, comment in fx.RESPONSES:
        if code in newest:
            await review_links.record_response(digest, d.ReviewSubmit(
                version_id=newest[code], region_code=code, decision=decision, comment=comment, reviewer_name=name))  # type: ignore[arg-type]
            done["review_responses"] += 1
    return done
