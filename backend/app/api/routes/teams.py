"""Teams and roles, workspace settings, usage (Settings stream). Writes require a signed-in, non-anonymous account."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Limit, Offset, RegisteredUser
from app.schemas import teams as v
from app.schemas import usage as usage_schema
from app.schemas.common import DataMode
from app.services import teams, usage

router = APIRouter(tags=["teams"])
Days = Annotated[int, Query(ge=1, le=365, description="Look-back window in days.")]


@router.post("/workspaces", status_code=status.HTTP_201_CREATED, response_model=v.WorkspaceDetail)
async def create_workspace(body: v.WorkspaceCreate, user: RegisteredUser) -> v.WorkspaceDetail:
    """Create a team workspace; the caller becomes its first owner."""
    return await teams.create_workspace(user.id, body)


@router.get("/workspaces/{workspace_id}", response_model=v.WorkspaceDetail)
async def get_workspace(workspace_id: UUID, user: CurrentUser) -> v.WorkspaceDetail:
    """Name, kind, the caller's role, member count and default regions. 404 for a non-member."""
    return await teams.get_workspace(user.id, workspace_id)


@router.patch("/workspaces/{workspace_id}", response_model=v.WorkspaceDetail)
async def update_workspace(workspace_id: UUID, body: v.WorkspacePatch, user: RegisteredUser) -> v.WorkspaceDetail:
    """Owner only: rename the workspace or set its default regions."""
    return await teams.update_workspace(user.id, workspace_id, body)


@router.get("/workspaces/{workspace_id}/members", response_model=v.TeamMemberPage)
async def list_members(workspace_id: UUID, user: CurrentUser, limit: Limit = 100, offset: Offset = 0) -> v.TeamMemberPage:
    return await teams.list_members(user.id, workspace_id, limit, offset)


@router.patch("/workspaces/{workspace_id}/members/{member_id}", response_model=v.TeamMember)
async def change_member_role(workspace_id: UUID, member_id: UUID, body: v.MemberRolePatch, user: RegisteredUser) -> v.TeamMember:
    """Owner only. The last owner cannot be demoted (409)."""
    return await teams.change_role(user.id, workspace_id, member_id, body)


@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(workspace_id: UUID, member_id: UUID, user: RegisteredUser) -> Response:
    """Owner only. The last owner cannot be removed (409)."""
    await teams.remove_member(user.id, workspace_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspaces/{workspace_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_workspace(workspace_id: UUID, user: RegisteredUser) -> Response:
    """Any member may leave, except the last owner (409) and the owner of their own personal workspace (409)."""
    await teams.leave_workspace(user.id, workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspaces/{workspace_id}/invites", status_code=status.HTTP_201_CREATED, response_model=v.TeamInviteCreated)
async def create_invite(workspace_id: UUID, body: v.TeamInviteCreate, user: RegisteredUser) -> v.TeamInviteCreated:
    """Owner only. Stores an invite and returns its code once. Nothing is emailed: the owner shares the code."""
    return await teams.create_invite(user.id, workspace_id, body)


@router.get("/workspaces/{workspace_id}/invites", response_model=v.TeamInvitePage)
async def list_invites(workspace_id: UUID, user: RegisteredUser, limit: Limit = 50, offset: Offset = 0) -> v.TeamInvitePage:
    """Owner only. Codes are never returned; only their status."""
    return await teams.list_invites(user.id, workspace_id, limit, offset)


@router.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(workspace_id: UUID, invite_id: UUID, user: RegisteredUser) -> Response:
    await teams.revoke_invite(user.id, workspace_id, invite_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/preview", response_model=v.InvitePreview)
async def preview_invite(body: v.InviteCodeBody, user: RegisteredUser) -> v.InvitePreview:
    """What the code offers (workspace name and role), so a person can decide before accepting. 404 for any invalid code."""
    return await teams.preview_invite(user.id, body.code)


@router.post("/invites/accept", response_model=v.WorkspaceDetail)
async def accept_invite(body: v.InviteCodeBody, user: RegisteredUser) -> v.WorkspaceDetail:
    """Join the workspace the code belongs to, with the invited role. A code works once."""
    return await teams.accept_invite(user.id, body.code)


@router.get("/workspaces/{workspace_id}/audit", response_model=v.TeamAuditPage)
async def list_team_audit(workspace_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0) -> v.TeamAuditPage:
    """Owner only. Membership, invite and settings changes, newest first."""
    return await teams.list_audit(user.id, workspace_id, limit, offset)


Mode = Annotated[DataMode, Query(description="`live` (default) counts live projects; `demo` counts the demo project.")]


@router.get("/workspaces/{workspace_id}/usage", response_model=v.WorkspaceUsage)
async def get_workspace_usage(workspace_id: UUID, user: CurrentUser, days: Days = 30, mode: Mode = "live") -> v.WorkspaceUsage:
    """Model calls, tokens and ESTIMATED cost recorded for the workspace. Owners see the whole workspace, other roles only
    their own calls. A call with no recorded cost is counted, never priced as 0. Actual cost is not reported."""
    return await usage.workspace_usage(user.id, workspace_id, days, mode)


@router.get("/workspaces/{workspace_id}/usage/report", response_model=usage_schema.UsageReport)
async def get_usage_report(workspace_id: UUID, user: CurrentUser, days: Days = 30, mode: Mode = "live") -> usage_schema.UsageReport:
    """The full Usage and Credits report: the summary plus spend and calls per day, the project, campaign, user and run
    breakdowns, today against the daily budget, and failed calls with their error codes. Same access rule as the summary."""
    return await usage.usage_report(user.id, workspace_id, days, mode)
