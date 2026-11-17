"""Users, personal workspaces and workspace membership.

`resolve_user` maps a verified token (`app.core.auth.Identity`) to the internal user id, creating the user and a
personal workspace on first sign-in. Every other module keeps using internal UUIDs; Firebase uids never leave this file.
"""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity
from app.core.errors import Forbidden, NotFound
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session

WRITE_ROLES = frozenset({"owner", "editor"})  # change projects, start runs
REVIEW_ROLES = frozenset({"owner", "editor", "reviewer"})  # also resolve evidence conflicts
READ_ONLY = "Your role in this workspace is read-only."


async def resolve_user(identity: Identity) -> m.User:
    """The user a token names. First sign-in creates the user and a personal workspace (one transaction)."""
    if identity.user_id is not None:  # dev token: the id is known; make sure the row exists
        async with read_session() as s:
            user = await s.get(m.User, identity.user_id)
        if user is not None:
            return user
        return await _create(identity, identity.user_id)
    assert identity.firebase_uid is not None
    async with read_session() as s:
        user = (await s.execute(select(m.User).where(m.User.firebase_uid == identity.firebase_uid))).scalar_one_or_none()
    if user is None:
        return await _create(identity, uuid4())
    if _profile_changed(user, identity):
        async with session() as s, s.begin():
            user = await s.get(m.User, user.id)  # type: ignore[assignment]
            assert user is not None
            user.is_anonymous, user.email = identity.is_anonymous, identity.email or user.email
            user.display_name = identity.display_name or user.display_name
    return user


def _profile_changed(user: m.User, identity: Identity) -> bool:
    return (
        user.is_anonymous != identity.is_anonymous
        or (identity.email is not None and identity.email != user.email)
        or (identity.display_name is not None and identity.display_name != user.display_name)
    )


async def _create(identity: Identity, user_id: UUID) -> m.User:
    try:
        async with session() as s, s.begin():
            user = await ensure_user(
                s, user_id, firebase_uid=identity.firebase_uid, email=identity.email,
                display_name=identity.display_name, is_anonymous=identity.is_anonymous,
            )
            await ensure_personal_workspace(s, user_id)
        return user
    except IntegrityError:  # a concurrent first request created the same user; theirs wins
        async with read_session() as s:
            query = select(m.User).where(
                m.User.id == user_id if identity.firebase_uid is None else m.User.firebase_uid == identity.firebase_uid
            )
            return (await s.execute(query)).scalar_one()


async def ensure_user(
    s: AsyncSession, user_id: UUID, *, firebase_uid: str | None = None, email: str | None = None,
    display_name: str | None = None, is_anonymous: bool = False,
) -> m.User:
    user = await s.get(m.User, user_id)
    if user is None:
        user = m.User(
            id=user_id, firebase_uid=firebase_uid, email=email, display_name=display_name, is_anonymous=is_anonymous,
            created_at=utcnow(),
        )
        s.add(user)
        await s.flush()
    return user


async def ensure_personal_workspace(s: AsyncSession, user_id: UUID) -> UUID:
    """The id of the user's personal workspace; creates the user row, the workspace and the owner membership if missing."""
    existing = await _personal_workspace_id(s, user_id)
    if existing is not None:
        return existing
    user = await ensure_user(s, user_id)
    now = utcnow()
    workspace_id = uuid4()
    try:
        async with s.begin_nested():  # a partial unique index allows one personal workspace per user
            s.add(m.Workspace(
                id=workspace_id, name=f"{user.display_name or 'My'} workspace", kind="personal", created_by=user_id,
                created_at=now,
            ))
            await s.flush()
            s.add(m.WorkspaceMember(id=uuid4(), workspace_id=workspace_id, user_id=user_id, role="owner", created_at=now))
            await s.flush()
    except IntegrityError:
        existing = await _personal_workspace_id(s, user_id)
        if existing is None:
            raise
        return existing
    return workspace_id


async def _personal_workspace_id(s: AsyncSession, user_id: UUID) -> UUID | None:
    return await s.scalar(
        select(m.Workspace.id).where(m.Workspace.created_by == user_id, m.Workspace.kind == "personal")
    )


async def member_role(s: AsyncSession, user_id: UUID, workspace_id: UUID) -> str | None:
    return await s.scalar(
        select(m.WorkspaceMember.role).where(
            m.WorkspaceMember.workspace_id == workspace_id, m.WorkspaceMember.user_id == user_id
        )
    )


async def require_workspace_role(
    s: AsyncSession, user_id: UUID, workspace_id: UUID, allowed: frozenset[str] | None = None
) -> str:
    """The caller's role in the workspace. A non-member gets 404 (the workspace is indistinguishable from a missing one);
    a member whose role is not in `allowed` gets 403."""
    role = await member_role(s, user_id, workspace_id)
    if role is None:
        raise NotFound("Workspace was not found.")
    if allowed is not None and role not in allowed:
        raise Forbidden(READ_ONLY)
    return role


async def list_workspaces(user_id: UUID) -> list[tuple[m.Workspace, str]]:
    async with read_session() as s:
        rows = await s.execute(
            select(m.Workspace, m.WorkspaceMember.role)
            .join(m.WorkspaceMember, m.WorkspaceMember.workspace_id == m.Workspace.id)
            .where(m.WorkspaceMember.user_id == user_id)
            .order_by(m.Workspace.created_at, m.Workspace.id)
        )
        return [(workspace, role) for workspace, role in rows.all()]
