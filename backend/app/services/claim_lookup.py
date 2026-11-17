"""Fetch one claim the way a link to it needs: its five tags, sources, and whether it is in an open conflict."""

from uuid import UUID

from sqlalchemy import or_, select

from app.core.errors import NotFound
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas.regions import ClaimView
from app.services.claims import _claim_view, _open_conflicts_by_claim, _sources
from app.services.identity import require_workspace_role


async def get_claim_view(user_id: UUID, workspace_id: UUID, claim_id: UUID) -> ClaimView:
    """A claim the workspace can see: its own or a shared one. Another workspace's claim is a 404, like a missing one."""
    async with read_session() as s:
        await require_workspace_role(s, user_id, workspace_id)
        claim = await s.scalar(select(m.Claim).where(
            m.Claim.id == claim_id, or_(m.Claim.workspace_id == workspace_id, m.Claim.workspace_id.is_(None))))
        if claim is None:
            raise NotFound("Claim was not found.")
        sources: dict[UUID, list[m.ClaimSource]] = {claim.id: await _sources(s, [claim.id])}
        open_by_claim = await _open_conflicts_by_claim(s, workspace_id)
    return _claim_view(claim, sources, open_by_claim, utcnow())

