"""Teams and roles, workspace settings and the workspace usage panel (Settings stream, Tier 1 feature 54).

Invites are stored records: nothing is emailed in this build. The invite `code` appears once, in the response that
creates the invite; afterwards only a hash exists. Usage figures are estimates from the gateway's price table.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, DataMode, Page
from app.schemas.identity import WorkspaceKind, WorkspaceRole

InviteEmail = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
WorkspaceTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
InviteStatus = Literal["pending", "accepted", "revoked", "expired"]
TeamAuditAction = Literal[
    "workspace.created", "workspace.renamed", "workspace.regions_changed",
    "invite.created", "invite.revoked", "member.joined", "member.role_changed", "member.removed", "member.left",
]


class WorkspaceCreate(ApiModel):
    name: WorkspaceTitle


class WorkspacePatch(ApiModel):
    """Owner only. A field that is omitted is left as it is."""

    name: WorkspaceTitle | None = None
    default_region_codes: list[Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]] | None = Field(
        default=None, max_length=40,
        description="ISO 3166-2 region codes (for example IN-TN) suggested for new campaigns. Each must be an active region.",
    )


class WorkspaceDetail(ApiModel):
    id: UUID
    name: str
    kind: WorkspaceKind
    role: WorkspaceRole = Field(description="The caller's role in this workspace.")
    created_at: datetime
    member_count: int
    owner_count: int
    default_region_codes: list[str]
    settings_updated_at: datetime | None = Field(description="NULL until the settings are changed for the first time.")


class TeamPerson(ApiModel):
    """A user as shown to a teammate. Name falls back to the email, then to nothing: the client shows a short id."""

    user_id: UUID
    display_name: str | None
    email: str | None


class TeamMember(ApiModel):
    id: UUID = Field(description="The membership id (use it to change the role or remove the member).")
    person: TeamPerson
    role: WorkspaceRole
    joined_at: datetime
    is_you: bool


class TeamMemberPage(Page[TeamMember]):
    pass


class MemberRolePatch(ApiModel):
    role: WorkspaceRole


class TeamInviteCreate(ApiModel):
    email: InviteEmail
    role: WorkspaceRole = "editor"


class TeamInvite(ApiModel):
    id: UUID
    email: str
    role: WorkspaceRole
    status: InviteStatus = Field(description="`pending` becomes `expired` once `expires_at` has passed.")
    invited_by: TeamPerson | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class TeamInviteCreated(ApiModel):
    invite: TeamInvite
    code: str = Field(description="The invite code. Shown only in this response; only its hash is stored.")
    accept_path: str = Field(description="App path that accepts the invite, with the code in the URL fragment (never sent to a server).")
    emailed: Literal[False] = Field(description="Always false: this build has no email service. Share the code yourself.")


class TeamInvitePage(Page[TeamInvite]):
    pass


class InviteCodeBody(ApiModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=16, max_length=128)]


class InvitePreview(ApiModel):
    """What a person holding a code sees before accepting."""

    workspace_name: str
    role: WorkspaceRole
    invited_by: TeamPerson | None
    expires_at: datetime
    email_matches_account: bool | None = Field(
        description="NULL when the signed-in account has no email on record, so the invited address cannot be compared.",
    )
    already_member: bool


class TeamAuditEntry(ApiModel):
    id: UUID
    action: TeamAuditAction
    actor: TeamPerson | None = Field(description="NULL when the system acted.")
    target: TeamPerson | None = Field(description="The member the change concerns, where there is one.")
    invite_email: str | None
    role: WorkspaceRole | None
    previous_role: WorkspaceRole | None
    region_codes: list[str] | None
    created_at: datetime


class TeamAuditPage(Page[TeamAuditEntry]):
    pass


# --- usage (read-only, from ai_usage_events) -----------------------------------------------------------------------


class UsageBreakdownRow(ApiModel):
    key: str = Field(description="The capability, `provider / model`, or the id of a project, campaign, user or run (`none` when the call has none).")
    label: str | None = Field(default=None, description="A readable name for an id key; null for capability and model keys.")
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_cost_usd: float | None = Field(
        description="Sum of the recorded per-call estimates. Null when no call in the row has a recorded cost (not 0): see `calls_without_cost`."
    )
    calls_without_cost: int = Field(default=0, description="Calls that cost nothing was recorded for (a failed call, or no token usage reported). Not counted as 0.")
    fixture_calls: int = Field(default=0, description="Demonstration calls answered from saved fixtures: no model ran and nothing was billed.")
    price_known: bool | None = Field(default=None, description="Model rows only: false when the model is not in the price table, so the cost is a stand-in.")


class WorkspaceUsage(ApiModel):
    days: int
    since: datetime
    until: datetime
    scope: Literal["workspace", "own"] = Field(description="`workspace` for owners and admins; `own` for every other role (only the caller's calls).")
    mode: DataMode = Field(description="`live` counts live projects and calls outside any project; `demo` counts the demo project only.")
    calls: int
    failed_calls: int
    calls_without_cost: int
    fixture_calls: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_cost_usd: float | None = Field(
        description="Sum of the recorded per-call estimates from the price table. An estimate, not an invoice. Null when calls exist but none has a recorded cost."
    )
    actual_cost_usd: None = Field(description="Always null: provider billing is not read, so actual cost is not reported.")
    price_table_version: str
    by_capability: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    notes: list[str]
