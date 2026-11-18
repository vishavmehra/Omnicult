"""Teams and roles (Tier 1 feature 54) and workspace settings. The workspace usage summary lives in services/usage.py.

Authorization is server side and follows the tenancy rule (services.identity): a non-member gets 404 (the workspace is
indistinguishable from a missing one); a member without the needed role gets 403. Reading the team and the settings is open to
every member; changing the name, the default regions, the roles, the invites and reading the audit
trail is for owners. Anonymous (demo) accounts are stopped at the route (`RegisteredUser`).

Invites are stored records; nothing is emailed. The code is shown once and only its SHA-256 hash is stored. An invite is
single use, expires after INVITE_TTL and can be revoked. Every membership change writes one `audit_log` row (ids only).
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import teams as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.common import paginate
from app.services.identity import member_role

INVITE_TTL = timedelta(days=7)
MAX_MEMBERS = 50
MAX_OPEN_INVITES = 50
MAX_OWNED_TEAM_WORKSPACES = 10
OWNER_ONLY = "Only a workspace owner can do this."
LAST_OWNER = "A workspace needs at least one owner. Make someone else an owner first."
CREATOR_STAYS = "The person whose personal workspace this is must stay its owner."
INVALID_INVITE = "This invite is not valid. It may have expired, been revoked, or already been used."
AUDIT_ACTIONS = (
    "workspace.created", "workspace.renamed", "workspace.regions_changed", "invite.created", "invite.revoked",
    "member.joined", "member.role_changed", "member.removed", "member.left",
)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


# --- shared lookups -----------------------------------------------------------------------------------------------


async def _workspace_and_role(s: AsyncSession, user_id: UUID, workspace_id: UUID, *, owner: bool = False) -> tuple[m.Workspace, str]:
    """The workspace and the caller's role. 404 for a non-member; 403 when `owner` is required and the role is lower."""
    role = await member_role(s, user_id, workspace_id)
    workspace = await s.get(m.Workspace, workspace_id) if role is not None else None
    if role is None or workspace is None:
        raise NotFound("Workspace was not found.")
    if owner and role != "owner":
        raise Forbidden(OWNER_ONLY)
    return workspace, role


async def _owner_rows(s: AsyncSession, workspace_id: UUID) -> list[m.WorkspaceMember]:
    """The owners, locked for the rest of the transaction (Postgres) so two demotions cannot both pass the last-owner check."""
    stmt = select(m.WorkspaceMember).where(m.WorkspaceMember.workspace_id == workspace_id, m.WorkspaceMember.role == "owner")
    return list((await s.execute(stmt.with_for_update())).scalars())


async def _users(s: AsyncSession, ids: set[UUID | None]) -> dict[UUID, m.User]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {u.id: u for u in (await s.execute(select(m.User).where(m.User.id.in_(wanted)))).scalars()}


def _person(users: dict[UUID, m.User], user_id: UUID | None) -> v.TeamPerson | None:
    if user_id is None:
        return None
    user = users.get(user_id)
    return v.TeamPerson(user_id=user_id, display_name=user.display_name if user else None, email=user.email if user else None)


async def _counts(s: AsyncSession, workspace_id: UUID) -> tuple[int, int]:
    members = await s.scalar(select(func.count(m.WorkspaceMember.id)).where(m.WorkspaceMember.workspace_id == workspace_id))
    owners = await s.scalar(select(func.count(m.WorkspaceMember.id)).where(
        m.WorkspaceMember.workspace_id == workspace_id, m.WorkspaceMember.role == "owner"))
    return int(members or 0), int(owners or 0)


async def _detail(s: AsyncSession, workspace: m.Workspace, role: str) -> v.WorkspaceDetail:
    settings = await s.get(m.WorkspaceSettings, workspace.id)
    members, owners = await _counts(s, workspace.id)
    return v.WorkspaceDetail(
        id=workspace.id, name=workspace.name, kind=workspace.kind,  # type: ignore[arg-type]
        role=role, created_at=workspace.created_at,  # type: ignore[arg-type]
        member_count=members, owner_count=owners,
        default_region_codes=list(settings.default_region_codes) if settings else [],
        settings_updated_at=settings.updated_at if settings else None,
    )


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


# --- workspaces -----------------------------------------------------------------------------------------------------


async def create_workspace(user_id: UUID, body: v.WorkspaceCreate) -> v.WorkspaceDetail:
    """A new team workspace; the caller becomes its first owner."""
    async with session() as s, s.begin():
        owned = await s.scalar(select(func.count(m.Workspace.id)).where(m.Workspace.created_by == user_id, m.Workspace.kind == "team"))
        if (owned or 0) >= MAX_OWNED_TEAM_WORKSPACES:
            raise Conflict(f"You can create up to {MAX_OWNED_TEAM_WORKSPACES} team workspaces.")
        now = utcnow()
        workspace = m.Workspace(id=uuid4(), name=body.name, kind="team", created_by=user_id, created_at=now)
        s.add(workspace)
        await s.flush()
        s.add(m.WorkspaceMember(id=uuid4(), workspace_id=workspace.id, user_id=user_id, role="owner", created_at=now))
        await record_audit(s, action="workspace.created", target_type="workspace", target_id=str(workspace.id),
                           workspace_id=workspace.id, actor_user_id=user_id)
        await s.flush()
        return await _detail(s, workspace, "owner")


async def get_workspace(user_id: UUID, workspace_id: UUID) -> v.WorkspaceDetail:
    async with read_session() as s:
        workspace, role = await _workspace_and_role(s, user_id, workspace_id)
        return await _detail(s, workspace, role)


async def update_workspace(user_id: UUID, workspace_id: UUID, patch: v.WorkspacePatch) -> v.WorkspaceDetail:
    async with session() as s, s.begin():
        workspace, role = await _workspace_and_role(s, user_id, workspace_id, owner=True)
        if patch.name is not None and patch.name != workspace.name:
            workspace.name = patch.name
            await record_audit(s, action="workspace.renamed", target_type="workspace", target_id=str(workspace.id),
                               workspace_id=workspace.id, actor_user_id=user_id)
        if patch.default_region_codes is not None:
            codes = list(dict.fromkeys(patch.default_region_codes))
            known = set((await s.execute(select(m.Region.code).where(m.Region.code.in_(codes), m.Region.is_active))).scalars()) if codes else set()
            unknown = [c for c in codes if c not in known]
            if unknown:
                raise _invalid("default_region_codes", "No such active region: " + ", ".join(unknown) + ".")
            settings = await s.get(m.WorkspaceSettings, workspace.id)
            if settings is None:
                s.add(m.WorkspaceSettings(workspace_id=workspace.id, default_region_codes=codes, updated_by=user_id, updated_at=utcnow()))
                changed = bool(codes)
            else:
                changed = list(settings.default_region_codes) != codes
                settings.default_region_codes, settings.updated_by, settings.updated_at = codes, user_id, utcnow()
            if changed:
                await record_audit(s, action="workspace.regions_changed", target_type="workspace", target_id=str(workspace.id),
                                   workspace_id=workspace.id, actor_user_id=user_id, detail={"region_codes": codes})
        await s.flush()
        return await _detail(s, workspace, role)


# --- members --------------------------------------------------------------------------------------------------------


async def list_members(user_id: UUID, workspace_id: UUID, limit: int, offset: int) -> v.TeamMemberPage:
    async with read_session() as s:
        await _workspace_and_role(s, user_id, workspace_id)
        order = case((m.WorkspaceMember.role == "owner", 0), (m.WorkspaceMember.role == "editor", 1),
                     (m.WorkspaceMember.role == "reviewer", 2), else_=3)
        stmt = select(m.WorkspaceMember).where(m.WorkspaceMember.workspace_id == workspace_id).order_by(
            order, m.WorkspaceMember.created_at, m.WorkspaceMember.id)
        rows, total = await paginate(s, stmt, limit, offset)
        users = await _users(s, {r.user_id for r in rows})
    items = [
        v.TeamMember(id=r.id, person=_person(users, r.user_id), role=r.role, joined_at=r.created_at,  # type: ignore[arg-type]
                     is_you=r.user_id == user_id)
        for r in rows
    ]
    return v.TeamMemberPage(items=items, limit=limit, offset=offset, total=total)


async def _member_view(s: AsyncSession, row: m.WorkspaceMember, caller: UUID) -> v.TeamMember:
    users = await _users(s, {row.user_id})
    return v.TeamMember(id=row.id, person=_person(users, row.user_id), role=row.role,  # type: ignore[arg-type]
                        joined_at=row.created_at, is_you=row.user_id == caller)


async def _get_member(s: AsyncSession, workspace_id: UUID, member_id: UUID) -> m.WorkspaceMember:
    row = await s.get(m.WorkspaceMember, member_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFound("Member was not found.")
    return row


async def _guard_leaving_owner(s: AsyncSession, workspace: m.Workspace, target: m.WorkspaceMember, new_role: str | None) -> None:
    """Refuse a change that would leave the workspace without an owner, or strip the creator of a personal workspace."""
    if target.role != "owner" or new_role == "owner":
        return
    if workspace.kind == "personal" and workspace.created_by == target.user_id:
        raise Conflict(CREATOR_STAYS)
    if len(await _owner_rows(s, workspace.id)) <= 1:
        raise Conflict(LAST_OWNER)


async def change_role(user_id: UUID, workspace_id: UUID, member_id: UUID, body: v.MemberRolePatch) -> v.TeamMember:
    async with session() as s, s.begin():
        workspace, _ = await _workspace_and_role(s, user_id, workspace_id, owner=True)
        target = await _get_member(s, workspace_id, member_id)
        if target.role != body.role:
            await _guard_leaving_owner(s, workspace, target, body.role)
            previous, target.role = target.role, body.role
            await record_audit(s, action="member.role_changed", target_type="member", target_id=str(target.id),
                               workspace_id=workspace_id, actor_user_id=user_id,
                               detail={"user_id": str(target.user_id), "role": body.role, "previous_role": previous})
            await s.flush()
        return await _member_view(s, target, user_id)


async def remove_member(user_id: UUID, workspace_id: UUID, member_id: UUID) -> None:
    async with session() as s, s.begin():
        workspace, _ = await _workspace_and_role(s, user_id, workspace_id, owner=True)
        target = await _get_member(s, workspace_id, member_id)
        await _drop(s, workspace, target, actor=user_id, action="member.removed")


async def leave_workspace(user_id: UUID, workspace_id: UUID) -> None:
    async with session() as s, s.begin():
        workspace, _ = await _workspace_and_role(s, user_id, workspace_id)
        target = (await s.execute(select(m.WorkspaceMember).where(
            m.WorkspaceMember.workspace_id == workspace_id, m.WorkspaceMember.user_id == user_id))).scalar_one()
        await _drop(s, workspace, target, actor=user_id, action="member.left")


async def _drop(s: AsyncSession, workspace: m.Workspace, target: m.WorkspaceMember, *, actor: UUID, action: str) -> None:
    await _guard_leaving_owner(s, workspace, target, None)
    await s.delete(target)
    await record_audit(s, action=action, target_type="member", target_id=str(target.id), workspace_id=workspace.id,
                       actor_user_id=actor, detail={"user_id": str(target.user_id), "role": target.role})
    await s.flush()


# --- invites --------------------------------------------------------------------------------------------------------


def _invite_status(row: m.WorkspaceInvite, now: datetime) -> str:
    return "expired" if row.status == "pending" and row.expires_at <= now else row.status


def _invite_view(row: m.WorkspaceInvite, users: dict[UUID, m.User], now: datetime) -> v.TeamInvite:
    return v.TeamInvite(
        id=row.id, email=row.email, role=row.role, status=_invite_status(row, now),  # type: ignore[arg-type]
        invited_by=_person(users, row.created_by), created_at=row.created_at, expires_at=row.expires_at,
        accepted_at=row.accepted_at, revoked_at=row.revoked_at,
    )


async def create_invite(user_id: UUID, workspace_id: UUID, body: v.TeamInviteCreate) -> v.TeamInviteCreated:
    async with session() as s, s.begin():
        workspace, _ = await _workspace_and_role(s, user_id, workspace_id, owner=True)
        now = utcnow()
        members, _owners = await _counts(s, workspace_id)
        pending_rows = list((await s.execute(select(m.WorkspaceInvite).where(
            m.WorkspaceInvite.workspace_id == workspace_id, m.WorkspaceInvite.status == "pending"))).scalars())
        for stale in (r for r in pending_rows if r.expires_at <= now):
            stale.status = "expired"  # frees the address for a fresh invite
        open_invites = [r for r in pending_rows if r.status == "pending"]
        if members + len(open_invites) >= MAX_MEMBERS:
            raise Conflict(f"A workspace holds up to {MAX_MEMBERS} members and open invites together.")
        member_with_email = await s.scalar(
            select(m.User.id).join(m.WorkspaceMember, m.WorkspaceMember.user_id == m.User.id)
            .where(m.WorkspaceMember.workspace_id == workspace_id, func.lower(m.User.email) == body.email))
        if member_with_email is not None:
            raise Conflict("That address already belongs to a member of this workspace.")
        if any(r.email == body.email for r in open_invites):
            raise Conflict("An invite for this address is already pending. Revoke it first to create a new one.")
        code = secrets.token_urlsafe(24)
        row = m.WorkspaceInvite(
            id=uuid4(), workspace_id=workspace.id, email=body.email, role=body.role, code_hash=hash_code(code),
            status="pending", created_by=user_id, created_at=now, expires_at=now + INVITE_TTL)
        s.add(row)
        await s.flush()
        await record_audit(s, action="invite.created", target_type="invite", target_id=str(row.id), workspace_id=workspace.id,
                           actor_user_id=user_id, detail={"role": body.role})
        await s.flush()
        users = await _users(s, {user_id})
        return v.TeamInviteCreated(invite=_invite_view(row, users, now), code=code, accept_path=f"/app/settings/join#code={code}",
                                   emailed=False)


async def list_invites(user_id: UUID, workspace_id: UUID, limit: int, offset: int) -> v.TeamInvitePage:
    async with read_session() as s:
        await _workspace_and_role(s, user_id, workspace_id, owner=True)
        now = utcnow()
        first = case((m.WorkspaceInvite.status == "pending", 0), else_=1)
        stmt = select(m.WorkspaceInvite).where(m.WorkspaceInvite.workspace_id == workspace_id).order_by(
            first, m.WorkspaceInvite.created_at.desc(), m.WorkspaceInvite.id)
        rows, total = await paginate(s, stmt, limit, offset)
        users = await _users(s, {r.created_by for r in rows})
    return v.TeamInvitePage(items=[_invite_view(r, users, now) for r in rows], limit=limit, offset=offset, total=total)


async def revoke_invite(user_id: UUID, workspace_id: UUID, invite_id: UUID) -> None:
    async with session() as s, s.begin():
        await _workspace_and_role(s, user_id, workspace_id, owner=True)
        row = await s.get(m.WorkspaceInvite, invite_id)
        if row is None or row.workspace_id != workspace_id:
            raise NotFound("Invite was not found.")
        if _invite_status(row, utcnow()) != "pending":
            raise Conflict("Only a pending invite can be revoked.")
        row.status, row.revoked_at = "revoked", utcnow()
        await record_audit(s, action="invite.revoked", target_type="invite", target_id=str(row.id), workspace_id=workspace_id,
                           actor_user_id=user_id, detail={"role": row.role})


async def _open_invite(s: AsyncSession, code: str, *, lock: bool) -> m.WorkspaceInvite:
    stmt = select(m.WorkspaceInvite).where(m.WorkspaceInvite.code_hash == hash_code(code))
    row = (await s.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if row is None or _invite_status(row, utcnow()) != "pending":
        raise NotFound(INVALID_INVITE)  # one message for unknown, used, revoked and expired: the code reveals nothing
    return row


def _email_matches(user: m.User, invite: m.WorkspaceInvite) -> bool | None:
    return None if not user.email else user.email.strip().lower() == invite.email


async def preview_invite(user_id: UUID, code: str) -> v.InvitePreview:
    async with read_session() as s:
        invite = await _open_invite(s, code, lock=False)
        user = await s.get(m.User, user_id)
        assert user is not None
        workspace = await s.get(m.Workspace, invite.workspace_id)
        assert workspace is not None
        users = await _users(s, {invite.created_by})
        existing = await member_role(s, user_id, workspace.id)
        return v.InvitePreview(
            workspace_name=workspace.name, role=invite.role,  # type: ignore[arg-type]
            invited_by=_person(users, invite.created_by), expires_at=invite.expires_at,
            email_matches_account=_email_matches(user, invite), already_member=existing is not None)


async def accept_invite(user_id: UUID, code: str) -> v.WorkspaceDetail:
    async with session() as s, s.begin():
        invite = await _open_invite(s, code, lock=True)
        user = await s.get(m.User, user_id)
        assert user is not None
        workspace = await s.get(m.Workspace, invite.workspace_id)
        assert workspace is not None
        if await member_role(s, user_id, workspace.id) is not None:
            raise Conflict("You are already a member of this workspace.")
        if _email_matches(user, invite) is False:
            raise Forbidden("This invite was issued for a different email address than the one on your account.")
        members, _owners = await _counts(s, workspace.id)
        if members >= MAX_MEMBERS:
            raise Conflict(f"This workspace already has {MAX_MEMBERS} members.")
        now = utcnow()
        member = m.WorkspaceMember(id=uuid4(), workspace_id=workspace.id, user_id=user_id, role=invite.role, created_at=now)
        s.add(member)
        invite.status, invite.accepted_by, invite.accepted_at = "accepted", user_id, now
        await s.flush()
        await record_audit(s, action="member.joined", target_type="member", target_id=str(member.id), workspace_id=workspace.id,
                           actor_user_id=user_id, detail={"user_id": str(user_id), "role": invite.role, "invite_id": str(invite.id)})
        await s.flush()
        return await _detail(s, workspace, invite.role)


# --- audit trail ----------------------------------------------------------------------------------------------------


async def list_audit(user_id: UUID, workspace_id: UUID, limit: int, offset: int) -> v.TeamAuditPage:
    async with read_session() as s:
        await _workspace_and_role(s, user_id, workspace_id, owner=True)
        stmt = select(m.AuditLog).where(m.AuditLog.workspace_id == workspace_id, m.AuditLog.action.in_(AUDIT_ACTIONS)).order_by(
            m.AuditLog.created_at.desc(), m.AuditLog.id)
        rows, total = await paginate(s, stmt, limit, offset)
        details = [r.detail or {} for r in rows]
        target_ids = {_uuid(d.get("user_id")) for d in details}
        users = await _users(s, {r.actor_user_id for r in rows} | target_ids)
        invite_ids = {_uuid(r.target_id) for r in rows if r.target_type == "invite"} - {None}
        emails: dict[UUID, str] = {}
        if invite_ids:
            emails = {i.id: i.email for i in (await s.execute(select(m.WorkspaceInvite).where(m.WorkspaceInvite.id.in_(invite_ids)))).scalars()}
    items = []
    for row, detail in zip(rows, details, strict=True):
        invite_id = _uuid(row.target_id) if row.target_type == "invite" else None
        items.append(v.TeamAuditEntry(
            id=row.id, action=row.action,  # type: ignore[arg-type]
            actor=_person(users, row.actor_user_id), target=_person(users, _uuid(detail.get("user_id"))),
            invite_email=emails.get(invite_id) if invite_id else None,
            role=detail.get("role"), previous_role=detail.get("previous_role"), region_codes=detail.get("region_codes"),
            created_at=row.created_at))
    return v.TeamAuditPage(items=items, limit=limit, offset=offset, total=total)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
