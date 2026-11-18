"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { campaignKeys } from "@/features/workspaces/campaign-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import type { BriefContent } from "./types";

export const deskKeys = {
  brief: (campaignId: string) => ["desk", "brief", campaignId] as const,
  versions: (campaignId: string) => ["desk", "brief-versions", campaignId] as const,
  version: (campaignId: string, version: number) => ["desk", "brief-version", campaignId, version] as const,
  kit: (projectId: string) => ["desk", "brand-kit", projectId] as const,
  today: (campaignId?: string) => ["desk", "today", campaignId ?? "all"] as const,
  regions: ["desk", "regions", "IN"] as const,
};

export function useBrief(campaignId: string) {
  return useQuery({
    queryKey: deskKeys.brief(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/brief", { params: { path: { campaign_id: campaignId } } })),
  });
}

export function useBriefVersions(campaignId: string) {
  return useQuery({
    queryKey: deskKeys.versions(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/brief/versions", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } }))).items,
  });
}

export function useBriefVersion(campaignId: string, version: number | null) {
  return useQuery({
    queryKey: deskKeys.version(campaignId, version ?? 0),
    enabled: version !== null,
    staleTime: Infinity, // a saved version never changes
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/brief/versions/{version}", { params: { path: { campaign_id: campaignId, version: version! } } })),
  });
}

/** The 36 states and union territories with their reference languages. Static reference data. */
export function useRegions() {
  return useQuery({
    queryKey: deskKeys.regions,
    staleTime: Infinity,
    queryFn: async () => (await unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: "IN", limit: 100 } } }))).items,
  });
}

export function useSaveBrief(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { content: BriefContent; changeNote: string | null; expectedVersion: number }) =>
      unwrap(
        api.PUT("/api/v1/campaigns/{campaign_id}/brief", {
          params: { path: { campaign_id: campaignId } },
          body: { content: input.content, change_note: input.changeNote, expected_version: input.expectedVersion },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(deskKeys.brief(campaignId), saved);
      void queryClient.invalidateQueries({ queryKey: deskKeys.versions(campaignId) });
      void queryClient.invalidateQueries({ queryKey: campaignKeys.detail(campaignId) }); // objective and regions are mirrored onto the campaign
      void queryClient.invalidateQueries({ queryKey: ["desk", "today"] });
      void queryClient.invalidateQueries({ queryKey: ["directory"] });
    },
  });
}

export function useBrandKit(projectId: string) {
  return useQuery({
    queryKey: deskKeys.kit(projectId),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/brand-kit", { params: { path: { project_id: projectId } } })),
  });
}

export function useSaveBrandKit(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { design: components["schemas"]["KitUpdate"]["design"]; expectedRevision: number }) =>
      unwrap(
        api.PUT("/api/v1/projects/{project_id}/brand-kit", {
          params: { path: { project_id: projectId } },
          body: { design: input.design, expected_revision: input.expectedRevision },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(deskKeys.kit(projectId), saved);
      void queryClient.invalidateQueries({ queryKey: ["desk", "today"] });
    },
  });
}

export function useToday(campaignId?: string) {
  return useQuery({
    queryKey: deskKeys.today(campaignId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/desk/today", { params: { query: { ...(campaignId ? { campaign_id: campaignId } : {}), limit: 30 } } })),
    refetchInterval: 30_000,
  });
}
