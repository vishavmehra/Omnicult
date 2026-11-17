"""Append-only audit log for important operations (who did what to which record)."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.db import models as m
from app.db.base import utcnow


async def record_audit(
    s: AsyncSession, *, action: str, target_type: str, target_id: str | None = None, workspace_id: UUID | None = None,
    actor_user_id: UUID | None = None, detail: dict[str, Any] | None = None,
) -> None:
    """Add one audit row to the caller's transaction. `detail` must not hold secrets or personal data beyond ids."""
    s.add(m.AuditLog(
        id=uuid4(), workspace_id=workspace_id, actor_user_id=actor_user_id, action=action, target_type=target_type,
        target_id=target_id, detail=detail, request_id=request_id_var.get() or None, created_at=utcnow(),
    ))
