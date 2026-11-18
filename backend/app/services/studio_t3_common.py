"""What the three Studio Tier 3 services (Format Fit, Claim Guard, Script Check) read the same way from a version."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.schemas.common import Anchor
from app.schemas.versions import TEXT_KINDS


def text_of(element: Mapping[str, Any]) -> str | None:
    """The checkable text of an element: its own string value. Audio and structured values have none."""
    value = element.get("value")
    if element.get("kind") in TEXT_KINDS and isinstance(value, str) and value.strip():
        return value
    return None


def _uuid(raw: Any) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def scene_timings(s: AsyncSession, campaign_id: UUID, elements: Sequence[Mapping[str, Any]]) -> dict[str, tuple[int, int | None]]:
    """Start and end of every scene the elements point at (X-Ray scenes of this campaign), by scene id as the element states it."""
    ids = {sid for e in elements if (sid := _uuid(e.get("scene_id")))}
    if not ids:
        return {}
    rows = (await s.execute(
        select(m.CreativeScene.id, m.CreativeScene.start_ms, m.CreativeScene.end_ms)
        .where(m.CreativeScene.campaign_id == campaign_id, m.CreativeScene.id.in_(ids))
    )).all()
    return {str(row.id): (row.start_ms, row.end_ms) for row in rows}


def anchor_of(element: Mapping[str, Any], timings: Mapping[str, tuple[int, int | None]]) -> Anchor:
    """Where an element is in the creative: its scene, the scene's time span and its box."""
    scene = element.get("scene_id")
    start, end = timings.get(str(scene), (None, None)) if scene else (None, None)
    return Anchor(scene_id=str(scene) if scene else None, start_ms=start, end_ms=end, bbox=element.get("bbox"))
