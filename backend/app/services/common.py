"""Access lookups, pagination, and small helpers shared by the services.

Access rule (contracts/README.md section 3): a project belongs to a workspace and the caller reaches it through
workspace membership. A resource in a workspace the caller is not a member of is indistinguishable from a missing
one (404). A member whose role is read-only (viewer, reviewer) gets 403 on writes. A resource the caller can reach but
that does not fit the request (another project or campaign, wrong run type, unfinished run) is 409.

Projects without a workspace (rows from before the 0008 backfill) fall back to the old rule: the owner has access.
"""

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.schemas.common import ErrorDetail
from app.services.identity import READ_ONLY, WRITE_ROLES

RowT = TypeVar("RowT")

ARCHIVED = "This project is archived and read-only."


def conflict(field: str, message: str) -> Conflict:
    return Conflict(message, details=[ErrorDetail(field=field, message=message)])


def not_found(what: str, field: str | None = None) -> NotFound:
    message = f"{what} was not found."
    return NotFound(message, details=[ErrorDetail(field=field, message=message)] if field else None)


def _role(project: m.Project, member_role: str | None, user_id: UUID) -> str | None:
    """The caller's role on a project: the workspace role, or owner of a pre-backfill project."""
    if project.workspace_id is None:
        return "owner" if project.owner_id == user_id else None
    return member_role


def _membership(user_id: UUID) -> Any:
    return and_(m.WorkspaceMember.workspace_id == m.Project.workspace_id, m.WorkspaceMember.user_id == user_id)


def visible_projects(user_id: UUID) -> Any:
    """SQL condition: projects in the caller's workspaces (or the caller's own pre-backfill projects)."""
    return or_(
        m.Project.workspace_id.in_(select(m.WorkspaceMember.workspace_id).where(m.WorkspaceMember.user_id == user_id)),
        and_(m.Project.workspace_id.is_(None), m.Project.owner_id == user_id),
    )


async def get_project(s: AsyncSession, user_id: UUID, project_id: UUID, *, writable: bool = False) -> m.Project:
    stmt = select(m.Project, m.WorkspaceMember.role).outerjoin(m.WorkspaceMember, _membership(user_id))
    found = (await s.execute(stmt.where(m.Project.id == project_id))).first()
    role = _role(found[0], found[1], user_id) if found is not None else None
    if found is None or role is None:
        raise not_found("Project")
    project = found[0]
    project.access_role = role
    if writable:
        require_writable(project)
    return project


async def get_owned(
    s: AsyncSession, model: type[RowT], row_id: UUID, user_id: UUID, what: str, field: str | None = None
) -> tuple[RowT, m.Project]:
    """Load a project-scoped row and its project, or raise 404 when the caller cannot reach its workspace."""
    stmt = (
        select(model, m.Project, m.WorkspaceMember.role)
        .join(m.Project, m.Project.id == model.project_id)  # type: ignore[attr-defined]
        .outerjoin(m.WorkspaceMember, _membership(user_id))
        .where(model.id == row_id)  # type: ignore[attr-defined]
    )
    found = (await s.execute(stmt)).first()
    role = _role(found[1], found[2], user_id) if found is not None else None
    if found is None or role is None:
        raise not_found(what, field)
    found[1].access_role = role
    return found[0], found[1]


def require_writable(project: m.Project) -> None:
    """Writes need an owner or editor role (viewers and reviewers read only) and an active project."""
    if project.access_role not in WRITE_ROLES:
        raise Forbidden(READ_ONLY)
    if project.status == "archived":
        raise Conflict(ARCHIVED)


async def paginate(s: AsyncSession, stmt: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    """One page of rows (scalars for single-entity selects, tuples otherwise) and the total count.

    The total comes from `count(*) OVER ()` in the same query, which saves one database round trip.
    A separate count runs only when the page is empty past the first offset.
    """
    single = len(stmt.column_descriptions) == 1
    result = (await s.execute(stmt.add_columns(func.count().over()).limit(limit).offset(offset))).all()
    if result:
        return [row[0] if single else tuple(row[:-1]) for row in result], int(result[0][-1])
    total = 0 if offset == 0 else await s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return [], int(total or 0)


def touch(project: m.Project) -> None:
    project.last_activity_at = utcnow()


def reject_null(field: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message="May not be null.")])


def apply_patch(row: object, changes: dict[str, Any], columns: dict[str, str], required: set[str]) -> None:
    """Copy PATCH fields onto a row. Explicit null is rejected for required fields."""
    for field, value in changes.items():
        if field not in columns:
            continue
        if value is None and field in required:
            raise reject_null(field)
        setattr(row, columns[field], value)
