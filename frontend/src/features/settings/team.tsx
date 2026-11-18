"use client";

import { Copy, LogOut, MailPlus, Trash2, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDate, formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  personName, ROLES, roleLabel, useAudit, useChangeRole, useCreateInvite, useInvites, useLeaveWorkspace, useMe, useMembers,
  useRemoveMember, useRevokeInvite, useWorkspaceDetail, type TeamAuditEntry, type TeamInvite, type TeamInviteCreated, type TeamMember, type WorkspaceRole,
} from "./api";
import { SELECT_CLASS, SettingsFrame } from "./frame";

const MEMBER_ROW = "grid gap-x-4 gap-y-1.5 px-4 py-3 sm:grid-cols-[minmax(0,1.6fr)_9rem_8rem_9.5rem] sm:items-center";
const INVITE_ROW = "grid gap-x-4 gap-y-1.5 px-4 py-3 sm:grid-cols-[minmax(0,1.6fr)_9rem_14rem_6rem] sm:items-center";

function RolesLegend() {
  return (
    <ContextPanel title="What each role can do">
      <dl className="space-y-3.5 text-[13.5px]">
        {ROLES.map((r) => (
          <div key={r.value} className="space-y-0.5">
            <dt className="font-semibold text-ink">{r.label}</dt>
            <dd className="text-ink-secondary">{r.can}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[12.5px] text-ink-muted">Roles are checked by the server on every request, not only hidden in this screen. A workspace always keeps at least one owner.</p>
    </ContextPanel>
  );
}

function MemberRow({ member, workspaceId, isOwner, ownerCount }: { member: TeamMember; workspaceId: string; isOwner: boolean; ownerCount: number }) {
  const router = useRouter();
  const change = useChangeRole(workspaceId);
  const remove = useRemoveMember(workspaceId);
  const leave = useLeaveWorkspace(workspaceId);
  const [confirming, setConfirming] = useState(false);
  const name = personName(member.person);
  const onlyOwner = member.role === "owner" && ownerCount <= 1;
  const error = change.error ?? remove.error ?? leave.error;
  const verb = member.is_you ? "Leave" : "Remove";

  return (
    <li>
      <div className={MEMBER_ROW}>
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-raised text-ink-secondary shadow-clay">
            <UserRound className="size-4" />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[14px] font-medium text-ink">
              {name}
              {member.is_you && <span className="ml-1.5 text-[12px] font-normal text-ink-muted">(you)</span>}
            </p>
            {member.person.email && member.person.display_name && <p className="type-meta truncate">{member.person.email}</p>}
          </div>
        </div>
        <div>
          {isOwner ? (
            <select
              aria-label={`Role for ${name}`}
              className={cn(SELECT_CLASS, "w-full")}
              value={member.role}
              disabled={change.isPending}
              onChange={(e) => change.mutate({ memberId: member.id, role: e.target.value as WorkspaceRole })}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-[13.5px] text-ink-body">{roleLabel(member.role)}</span>
          )}
        </div>
        <p className="type-meta" title={formatDateTime(member.joined_at)}>
          Joined {formatDate(member.joined_at)}
        </p>
        <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
          {confirming ? (
            <>
              <span className="text-[13px] text-ink-body">{member.is_you ? "Leave this workspace?" : `Remove ${name}?`}</span>
              <Button
                variant="destructive"
                disabled={remove.isPending || leave.isPending}
                onClick={() =>
                  member.is_you
                    ? leave.mutate(undefined, { onSuccess: () => router.replace("/app/settings") })
                    : remove.mutate(member.id, { onSuccess: () => setConfirming(false) })
                }
              >
                {verb}
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            (isOwner || member.is_you) && (
              <Button
                variant="outline"
                disabled={onlyOwner}
                title={onlyOwner ? "The only owner cannot leave or be removed. Make someone else an owner first." : undefined}
                onClick={() => setConfirming(true)}
              >
                {member.is_you ? <LogOut aria-hidden /> : <Trash2 aria-hidden />}
                {verb}
              </Button>
            )
          )}
        </div>
      </div>
      {error && <ErrorState error={error} className="mx-4 mb-3" />}
    </li>
  );
}

function useCopy() {
  const [done, setDone] = useState<string | null>(null);
  return {
    done,
    copy: async (key: string, text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setDone(key);
        setTimeout(() => setDone((d) => (d === key ? null : d)), 2500);
      } catch {
        setDone(null); // the code stays on screen to copy by hand
      }
    },
  };
}

function CopyRow({ id, label, value, copied, onCopy }: { id: string; label: string; value: string; copied: boolean; onCopy: (key: string, text: string) => void }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="type-meta block">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input id={id} readOnly value={value} onFocus={(e) => e.currentTarget.select()} className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-surface-muted px-2.5 font-mono text-[12px] text-ink shadow-well outline-none focus-visible:border-ring" />
        <Button variant="outline" onClick={() => onCopy(id, value)}>
          <Copy aria-hidden />
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

function CreatedInvite({ created }: { created: TeamInviteCreated }) {
  const { done, copy } = useCopy();
  const link = typeof window === "undefined" ? created.accept_path : `${window.location.origin}${created.accept_path}`;
  return (
    <div className="space-y-3 rounded-card border border-border-strong/50 bg-surface-muted/50 p-4" role="status">
      <p className="text-[14px] font-semibold text-ink">
        Invite for {created.invite.email} as {roleLabel(created.invite.role)}
      </p>
      <CopyRow id="invite-link" label="Invite link" value={link} copied={done === "invite-link"} onCopy={copy} />
      <CopyRow id="invite-code" label="Invite code" value={created.code} copied={done === "invite-code"} onCopy={copy} />
      <p className="text-[12.5px] text-ink-muted">
        Nothing is emailed; this build has no email service. Send the link or code yourself. It is shown only now, works once, and expires {formatDate(created.invite.expires_at)}.
      </p>
    </div>
  );
}

function InviteForm({ workspaceId }: { workspaceId: string }) {
  const create = useCreateInvite(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("editor");
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail("") });
        }}
      >
        <div className="min-w-0 flex-1 basis-60 space-y-1">
          <label htmlFor="invite-email" className="type-meta block">
            Email address
          </label>
          <Input id="invite-email" type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" className="h-10" />
        </div>
        <div className="space-y-1">
          <label htmlFor="invite-role" className="type-meta block">
            Role
          </label>
          <select id="invite-role" className={cn(SELECT_CLASS, "h-10")} value={role} onChange={(e) => setRole(e.target.value as WorkspaceRole)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" size="lg" disabled={!email.trim() || create.isPending}>
          <MailPlus aria-hidden />
          {create.isPending ? "Creating…" : "Create invite"}
        </Button>
      </form>
      {create.error && <ErrorState error={create.error} />}
      {create.data && <CreatedInvite created={create.data} />}
    </div>
  );
}

function InviteRow({ invite, workspaceId }: { invite: TeamInvite; workspaceId: string }) {
  const revoke = useRevokeInvite(workspaceId);
  const pending = invite.status === "pending";
  return (
    <li>
      <div className={INVITE_ROW}>
        <p className="min-w-0 truncate text-[14px] text-ink">{invite.email}</p>
        <p className="text-[13.5px] text-ink-body">{roleLabel(invite.role)}</p>
        <p className="type-meta first-letter:uppercase" title={formatDateTime(pending ? invite.expires_at : (invite.accepted_at ?? invite.revoked_at ?? invite.expires_at))}>
          {pending ? `Pending, expires ${formatRelative(invite.expires_at)}` : invite.status}
        </p>
        <div className="sm:text-right">
          {pending && (
            <Button variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate(invite.id)}>
              Revoke
            </Button>
          )}
        </div>
      </div>
      {revoke.error && <ErrorState error={revoke.error} className="mx-4 mb-3" />}
    </li>
  );
}

function describe(e: TeamAuditEntry): ReactNode {
  const actor = personName(e.actor);
  const target = personName(e.target);
  switch (e.action) {
    case "workspace.created":
      return `${actor} created the workspace`;
    case "workspace.renamed":
      return `${actor} renamed the workspace`;
    case "workspace.regions_changed":
      return e.region_codes?.length ? `${actor} set the default regions to ${e.region_codes.join(", ")}` : `${actor} cleared the default regions`;
    case "invite.created":
      return `${actor} invited ${e.invite_email ?? "someone"} as ${roleLabel(e.role)}`;
    case "invite.revoked":
      return `${actor} revoked the invite for ${e.invite_email ?? "someone"}`;
    case "member.joined":
      return `${target} joined as ${roleLabel(e.role)}`;
    case "member.role_changed":
      return `${actor} changed ${target} from ${roleLabel(e.previous_role)} to ${roleLabel(e.role)}`;
    case "member.removed":
      return `${actor} removed ${target} (${roleLabel(e.role)})`;
    case "member.left":
      return `${actor} left the workspace (was ${roleLabel(e.role)})`;
  }
}

function History({ workspaceId }: { workspaceId: string }) {
  const audit = useAudit(workspaceId, true);
  return (
    <section aria-labelledby="history" className="space-y-2">
      <SectionTitle id="history" meta={audit.data ? `${audit.data.total} ${audit.data.total === 1 ? "entry" : "entries"}` : undefined}>
        Membership history
      </SectionTitle>
      {audit.error ? (
        <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />
      ) : !audit.data ? (
        <LoadingState label="Loading the membership history…" />
      ) : audit.data.items.length === 0 ? (
        <EmptyState title="No changes recorded yet" description="Invites, joins, role changes, removals and workspace setting changes are recorded here, newest first." />
      ) : (
        <ol className="ledger-rules rounded-card border border-border bg-surface">
          {audit.data.items.map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5">
              <p className="min-w-0 text-[13.5px] text-ink-body">{describe(e)}</p>
              <time className="type-meta shrink-0" dateTime={e.created_at} title={formatDateTime(e.created_at)}>
                {formatRelative(e.created_at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TeamPanel({ workspaceId }: { workspaceId: string }) {
  const me = useMe();
  const detail = useWorkspaceDetail(workspaceId);
  const members = useMembers(workspaceId);
  const isOwner = detail.data?.role === "owner" && !me.data?.is_anonymous;
  const invites = useInvites(workspaceId, isOwner);
  const anonymous = Boolean(me.data?.is_anonymous);

  if (detail.error || members.error) {
    return <ErrorState error={detail.error ?? members.error} onRetry={() => { void detail.refetch(); void members.refetch(); }} />;
  }
  if (!detail.data || !members.data) return <LoadingState label="Loading the team…" />;

  return (
    <div className="space-y-8">
      <RolesLegend />
      <section aria-labelledby="members">
        <SectionTitle id="members" meta={`${members.data.total} ${members.data.total === 1 ? "member" : "members"}`}>
          Members of {detail.data.name}
        </SectionTitle>
        <ul className="ledger-rules rounded-card border border-border bg-surface">
          {members.data.items.map((m) => (
            <MemberRow key={m.id} member={m} workspaceId={workspaceId} isOwner={isOwner} ownerCount={detail.data.owner_count} />
          ))}
        </ul>
        {!isOwner && !anonymous && <p className="mt-2 text-[12.5px] text-ink-muted">Your role is {roleLabel(detail.data.role)}. Owners manage members and invites.</p>}
      </section>

      {anonymous ? (
        <EmptyState title="Sign in to manage a team" description="Demo visitors can look around but cannot invite people or change roles. Sign in with an account to create a team workspace." />
      ) : (
        isOwner && (
          <>
            <section aria-labelledby="invite" className="space-y-3">
              <SectionTitle id="invite">Invite someone</SectionTitle>
              <InviteForm workspaceId={workspaceId} />
            </section>
            <section aria-labelledby="open-invites" className="space-y-2">
              <SectionTitle id="open-invites" meta={invites.data ? `${invites.data.total}` : undefined}>
                Invites
              </SectionTitle>
              {invites.error ? (
                <ErrorState error={invites.error} onRetry={() => void invites.refetch()} />
              ) : !invites.data ? (
                <LoadingState label="Loading invites…" />
              ) : invites.data.items.length === 0 ? (
                <EmptyState title="No invites yet" description="An invite is a one-time code for one email address. Create one above and send it to the person yourself." />
              ) : (
                <ul className="ledger-rules rounded-card border border-border bg-surface">
                  {invites.data.items.map((i) => (
                    <InviteRow key={i.id} invite={i} workspaceId={workspaceId} />
                  ))}
                </ul>
              )}
            </section>
            <History workspaceId={workspaceId} />
          </>
        )
      )}
    </div>
  );
}

/** Teams and Roles (Tier 1 feature 54): members, roles, invites, leaving, and the membership history. */
export function TeamScreen() {
  return <SettingsFrame>{(workspace) => <TeamPanel key={workspace.id} workspaceId={workspace.id} />}</SettingsFrame>;
}
