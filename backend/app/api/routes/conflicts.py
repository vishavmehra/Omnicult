from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, Limit, Offset, RegisteredUser
from app.schemas.common import DataMode
from app.schemas.regions import Conflict, ConflictPage, ConflictResolveRequest, ConflictStatus
from app.services import claims

router = APIRouter(tags=["conflicts"])


@router.get("/workspaces/{workspace_id}/conflicts", response_model=ConflictPage)
async def list_conflicts(
    workspace_id: UUID,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
    region_code: Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")] = None,
    conflict_status: Annotated[ConflictStatus | None, Query(alias="status")] = None,
    mode: DataMode = "live",
) -> ConflictPage:
    """Disagreements between claims, unresolved first. Both claims, their sources, dates and scope are included."""
    items, total = await claims.list_conflicts(
        user.id, workspace_id, region_code=region_code, status=conflict_status, mode=mode, limit=limit, offset=offset
    )
    return ConflictPage(items=items, limit=limit, offset=offset, total=total)


@router.post("/workspaces/{workspace_id}/conflicts/{conflict_id}/resolve", response_model=Conflict)
async def resolve_conflict(
    workspace_id: UUID, conflict_id: UUID, body: ConflictResolveRequest, user: RegisteredUser
) -> Conflict:
    """Accept the value in use, switch to the other, or request a native review. Recorded with the user and time.
    Needs the owner, editor or reviewer role (403 otherwise); anonymous users get 403."""
    return await claims.resolve_conflict(user.id, workspace_id, conflict_id, body.decision, body.note)
