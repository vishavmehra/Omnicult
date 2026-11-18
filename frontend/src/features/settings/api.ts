"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type WorkspaceDetail = S["WorkspaceDetail"];
export type TeamMember = S["TeamMember"];
export type TeamPerson = S["TeamPerson"];
export type TeamInvite = S["TeamInvite"];
export type TeamInviteCreated = S["TeamInviteCreated"];
export type TeamAuditEntry = S["TeamAuditEntry"];
export type WorkspaceUsage = S["WorkspaceUsage"];
export type WorkspaceRole = WorkspaceDetail["role"];
export type CountryPack = S["CountryPack"];
export type InvitePreview = S["InvitePreview"];

export const ROLES: { value: WorkspaceRole; label: string; can: string }[] = [
  { value: "owner", label: "Owner", can: "Everything an editor can do, plus members, invites, workspace settings and the membership history." },
  { value: "editor", label: "Editor", can: "Change brands and campaigns, start runs and generate versions." },
  { value: "reviewer", label: "Reviewer", can: "Read everything and resolve evidence conflicts. Cannot change campaigns." },
  { value: "viewer", label: "Viewer", can: "Read only." },
];
export const roleLabel = (role: WorkspaceRole | null | undefined) => ROLES.find((r) => r.value === role)?.label ?? role ?? "";

export const keys = {
  me: ["settings", "me"] as const,
  ws: (id: string) => ["settings", "workspace", id] as const,
  members: (id: string) => ["settings", "workspace", id, "members"] as const,
  invites: (id: string) => ["settings", "workspace", id, "invites"] as const,
  audit: (id: string) => ["settings", "workspace", id, "audit"] as const,
  usage: (id: string, days: number) => ["settings", "workspace", id, "usage", days] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => unwrap(api.GET("/api/v1/me")) });
}

export function useWorkspaceDetail(id: string | null) {
  return useQuery({
    queryKey: keys.ws(id ?? ""), enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}", { params: { path: { workspace_id: id! } } })),
  });
}

export function useMembers(id: string | null) {
  return useQuery({
    queryKey: keys.members(id ?? ""), enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/members", { params: { path: { workspace_id: id! }, query: { limit: 100 } } })),
  });
}

/** Owner only: the server answers 403 to anyone else, so the query is disabled unless the caller is an owner. */
export function useInvites(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: keys.invites(id ?? ""), enabled: Boolean(id) && enabled,
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/invites", { params: { path: { workspace_id: id! }, query: { limit: 50 } } })),
  });
}

export function useAudit(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: keys.audit(id ?? ""), enabled: Boolean(id) && enabled,
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/audit", { params: { path: { workspace_id: id! }, query: { limit: 30 } } })),
  });
}

export function useUsage(id: string | null, days: number) {
  return useQuery({
    queryKey: keys.usage(id ?? "", days), enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/usage", { params: { path: { workspace_id: id! }, query: { days } } })),
  });
}

export function useCountryPack(code: string) {
  return useQuery({
    queryKey: ["settings", "country-pack", code], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/country-packs/{country_code}", { params: { path: { country_code: code } } })),
  });
}

export function useRegionList(code: string) {
  return useQuery({
    queryKey: ["settings", "regions", code], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: code, limit: 100 } } })),
  });
}

/** Refresh everything one workspace shows after a change to it. */
function useRefresh(workspaceId: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["settings", "workspace", workspaceId] });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/v1/workspaces", { body: { name } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useUpdateWorkspace(workspaceId: string) {
  const queryClient = useQueryClient();
  const refresh = useRefresh(workspaceId);
  return useMutation({
    mutationFn: (body: { name?: string; default_region_codes?: string[] }) =>
      unwrap(api.PATCH("/api/v1/workspaces/{workspace_id}", { params: { path: { workspace_id: workspaceId } }, body })),
    onSuccess: async () => {
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: keys.me })]);
    },
  });
}

export function useChangeRole(workspaceId: string) {
  const refresh = useRefresh(workspaceId);
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: WorkspaceRole }) =>
      unwrap(api.PATCH("/api/v1/workspaces/{workspace_id}/members/{member_id}", { params: { path: { workspace_id: workspaceId, member_id: memberId } }, body: { role } })),
    onSettled: refresh,
  });
}

export function useRemoveMember(workspaceId: string) {
  const refresh = useRefresh(workspaceId);
  return useMutation({
    mutationFn: (memberId: string) =>
      unwrap(api.DELETE("/api/v1/workspaces/{workspace_id}/members/{member_id}", { params: { path: { workspace_id: workspaceId, member_id: memberId } } })),
    onSettled: refresh,
  });
}

export function useLeaveWorkspace(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/workspaces/{workspace_id}/leave", { params: { path: { workspace_id: workspaceId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useCreateInvite(workspaceId: string) {
  const refresh = useRefresh(workspaceId);
  return useMutation({
    mutationFn: (body: { email: string; role: WorkspaceRole }) =>
      unwrap(api.POST("/api/v1/workspaces/{workspace_id}/invites", { params: { path: { workspace_id: workspaceId } }, body })),
    onSuccess: refresh,
  });
}

export function useRevokeInvite(workspaceId: string) {
  const refresh = useRefresh(workspaceId);
  return useMutation({
    mutationFn: (inviteId: string) =>
      unwrap(api.DELETE("/api/v1/workspaces/{workspace_id}/invites/{invite_id}", { params: { path: { workspace_id: workspaceId, invite_id: inviteId } } })),
    onSettled: refresh,
  });
}

export function usePreviewInvite() {
  return useMutation({ mutationFn: (code: string) => unwrap(api.POST("/api/v1/invites/preview", { body: { code } })) });
}

export function useAcceptInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => unwrap(api.POST("/api/v1/invites/accept", { body: { code } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
  });
}

/** A person's name, else their email, else a short id: dev accounts and new sign-ins may have neither. */
export function personName(p: TeamPerson | null | undefined) {
  if (!p) return "The system";
  return p.display_name || p.email || `User ${p.user_id.slice(0, 8)}`;
}
