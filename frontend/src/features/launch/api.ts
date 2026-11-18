"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useCampaign } from "@/features/workspaces/campaign-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import type {
  ApprovalCreate,
  Capabilities,
  MemberRole,
  ReadinessRequest,
  ReadinessVerdict,
  ScoreCompareRequest,
  VersionOption,
} from "./types";

const root = (campaignId: string) => ["launch", campaignId] as const;
export const launchKeys = {
  board: (c: string) => [...root(c), "board"] as const,
  history: (c: string) => [...root(c), "history"] as const,
  approvals: (c: string) => [...root(c), "approvals"] as const,
  rules: (c: string) => [...root(c), "rules"] as const,
  versions: (c: string) => [...root(c), "versions"] as const,
};

const path = (campaign_id: string) => ({ params: { path: { campaign_id } } });

export function useReadinessBoard(campaignId: string) {
  return useQuery({
    queryKey: launchKeys.board(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/readiness", path(campaignId))),
  });
}

/** The documented rules and named thresholds. They change only with the rule version, so one read is enough. */
export function useReadinessRules(campaignId: string) {
  return useQuery({
    queryKey: launchKeys.rules(campaignId),
    staleTime: Infinity,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/readiness/rules", path(campaignId))),
  });
}

/** Every stored verdict and every human decision, newest first (one page of up to 100 each: enough for a campaign). */
export function useHistory(campaignId: string) {
  const verdicts = useQuery({
    queryKey: [...launchKeys.history(campaignId), "verdicts"],
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/readiness/history", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } })),
  });
  const approvals = useQuery({
    queryKey: [...launchKeys.approvals(campaignId), "list"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/approvals", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } })),
  });
  return { verdicts, approvals };
}

export function useRegions() {
  return useQuery({
    // Own key: Studio caches the whole regions page under ["regions", "IN"]; this caches only `items` (a shared key crashed Launch).
    queryKey: ["regions", "IN", "items"],
    staleTime: 10 * 60_000,
    queryFn: async () => (await unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: "IN", limit: 100 } } }))).items,
  });
}

export function useMe() {
  return useQuery({ queryKey: ["me"], staleTime: 60_000, queryFn: () => unwrap(api.GET("/api/v1/me")) });
}

/**
 * The versions that can be scored: Creative Studio versions when there are any, else the campaign's content versions.
 * Oldest first, so the original keeps its place (A) in comparisons.
 */
export function useVersionOptions() {
  const { campaign } = useCampaign();
  const studio = useQuery({
    queryKey: launchKeys.versions(campaign.id),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions", { params: { path: { campaign_id: campaign.id }, query: { limit: 100 } } }))).items,
  });
  const options: VersionOption[] =
    studio.data && studio.data.length > 0
      ? [...studio.data]
          .sort((a, b) => a.created_at.localeCompare(b.created_at))
          .map((v) => ({ id: v.id, label: v.label, source: "studio", regionCode: v.region_code, language: v.language }))
      : [...campaign.versions]
          .sort((a, b) => a.version_number - b.version_number)
          .map((v) => ({ id: v.id, label: `Content version v${v.version_number}`, source: "content", regionCode: null, language: null }));
  return { options, isPending: studio.isPending, error: studio.error, refetch: studio.refetch, hasStudioVersions: (studio.data?.length ?? 0) > 0 };
}

const ROLES: MemberRole[] = ["owner", "editor", "reviewer", "viewer"];

/** Roles: owner and editor compute verdicts; owner, editor and reviewer record decisions; a viewer only reads. */
export function useCapabilities(): Capabilities & { loading: boolean } {
  const { project } = useCampaign();
  const me = useMe();
  if (me.isPending) return { role: null, signedIn: false, canCompute: false, canDecide: false, reason: null, loading: true };
  const found = me.data?.workspaces.find((w) => w.id === project.workspace_id)?.role;
  const role = ROLES.find((r) => r === found) ?? null;
  const signedIn = Boolean(me.data) && !me.data!.is_anonymous;
  const archived = project.status === "archived";
  const canCompute = !archived && (role === "owner" || role === "editor");
  const canDecide = !archived && signedIn && (role === "owner" || role === "editor" || role === "reviewer");
  let reason: string | null = null;
  if (archived) reason = "This brand is archived, so verdicts and decisions are read-only.";
  else if (role === "viewer") reason = "Your role in this workspace is viewer. Viewers can read scores, verdicts and decisions, but cannot compute verdicts or approve.";
  else if (role === "reviewer") reason = "Your role is reviewer. Reviewers can approve, reject or request changes; computing a verdict needs the owner or editor role.";
  else if (role === null) reason = "Your role in this workspace could not be determined, so actions that change records are off.";
  else if (!signedIn) reason = "Sign in to record decisions. An anonymous session can read verdicts but not approve.";
  return { role, signedIn, canCompute, canDecide, reason, loading: false };
}

export function useCompareScores(campaignId: string) {
  return useMutation({
    mutationFn: (body: ScoreCompareRequest) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/scores/compare", { ...path(campaignId), body })),
  });
}

/** 201 means a new verdict was stored; 200 means identical inputs under the same rules, so the newest stored one came back. */
export function useComputeReadiness(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ReadinessRequest): Promise<{ verdict: ReadinessVerdict; created: boolean }> => {
      let status = 0;
      const verdict = await unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/readiness", { ...path(campaignId), body }).then((r) => {
          status = r.response.status;
          return r;
        }),
      );
      return { verdict, created: status === 201 };
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: launchKeys.board(campaignId) });
      void queryClient.invalidateQueries({ queryKey: launchKeys.history(campaignId) });
    },
  });
}

export function useRecordApproval(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ApprovalCreate) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/approvals", { ...path(campaignId), body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: launchKeys.board(campaignId) });
      void queryClient.invalidateQueries({ queryKey: launchKeys.approvals(campaignId) });
    },
  });
}

/** The Evidence Meter reading for a region (Market Lens). The one observation Omnicult can already read for this room. */
export function fetchEvidenceMeter(workspaceId: string, regionCode: string) {
  return unwrap(
    api.GET("/api/v1/workspaces/{workspace_id}/regions/{region_code}/evidence-meter", {
      params: { path: { workspace_id: workspaceId, region_code: regionCode } },
    }),
  );
}
