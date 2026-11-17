"""The signed-in user and their workspaces."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import ApiModel

WorkspaceRole = Literal["owner", "editor", "reviewer", "viewer"]
WorkspaceKind = Literal["personal", "team"]


class Workspace(ApiModel):
    id: UUID
    name: str
    kind: WorkspaceKind
    role: WorkspaceRole
    created_at: datetime


class Me(ApiModel):
    id: UUID
    email: str | None
    display_name: str | None
    is_anonymous: bool
    workspaces: list[Workspace]
