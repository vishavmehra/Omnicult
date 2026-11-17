from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser
from app.core.errors import Unauthenticated
from app.db import models as m
from app.db.session import read_session
from app.schemas.identity import Me, Workspace
from app.services.identity import list_workspaces

router = APIRouter(tags=["workspaces"])


@router.get("/me", response_model=Me)
async def get_me(user: CurrentUser) -> Me:
    """The signed-in user and the workspaces they belong to, with their role in each."""
    async with read_session() as s:
        row = (await s.execute(select(m.User).where(m.User.id == user.id))).scalar_one_or_none()
    if row is None:  # the user was removed after the token was verified
        raise Unauthenticated("The access token is missing, invalid, or expired. Sign in again.")
    workspaces = [
        Workspace(id=w.id, name=w.name, kind=w.kind, role=role, created_at=w.created_at)  # type: ignore[arg-type]
        for w, role in await list_workspaces(user.id)
    ]
    return Me(
        id=row.id, email=row.email, display_name=row.display_name, is_anonymous=row.is_anonymous, workspaces=workspaces
    )
