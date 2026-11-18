"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useRun } from "@/lib/api/runs";
import type { components } from "@/lib/api/schema";

export type RemakeOutput = components["schemas"]["RemakeOutput"];
export type RemakeCapabilities = components["schemas"]["RemakeCapabilities"];
export type VisualRemake = components["schemas"]["VisualRemake"];
export type SoundRemake = components["schemas"]["SoundRemake"];
export type VisualRequest = components["schemas"]["RemakeVisualRequest"];
export type SoundRequest = components["schemas"]["RemakeSoundRequest"];
export type VersionSummary = components["schemas"]["VersionSummary"];
export type VersionNode = components["schemas"]["VersionNode"];
export type CreativeElement = components["schemas"]["CreativeElement-Output"];
export type ImageAsset = components["schemas"]["Asset"];

export const remakeKeys = {
  caps: (campaignId: string) => ["remake", "capabilities", campaignId] as const,
  list: (campaignId: string) => ["remake", "list", campaignId] as const,
  versions: (campaignId: string) => ["remake", "versions", campaignId] as const,
  version: (campaignId: string, versionId: string) => ["remake", "version", campaignId, versionId] as const,
  locks: (campaignId: string) => ["remake", "locks", campaignId] as const,
  images: (projectId: string) => ["remake", "images", projectId] as const,
};

export function useRemakeCapabilities(campaignId: string) {
  return useQuery({
    queryKey: remakeKeys.caps(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/remakes/capabilities", { params: { path: { campaign_id: campaignId } } })),
  });
}

/** Applied remakes of the campaign, newest first. */
export function useRemakes(campaignId: string) {
  return useQuery({
    queryKey: remakeKeys.list(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/remakes", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } }))).items,
  });
}

/** Every version node of the campaign, oldest first. */
export function useVersionList(campaignId: string) {
  return useQuery({
    queryKey: remakeKeys.versions(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } }))).items,
  });
}

/** One version with its elements. */
export function useVersion(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: remakeKeys.version(campaignId, versionId ?? "none"),
    enabled: Boolean(versionId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}", { params: { path: { campaign_id: campaignId, version_id: versionId! } } })),
  });
}

/** Ids of the elements locked right now. */
export function useActiveLocks(campaignId: string) {
  return useQuery({
    queryKey: remakeKeys.locks(campaignId),
    queryFn: async () =>
      new Set(
        (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/locks", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } }))).items.map(
          (l) => l.element_id,
        ),
      ),
  });
}

/** The project's uploaded images (derived files are hidden by the API). */
export function useProjectImages(projectId: string) {
  return useQuery({
    queryKey: remakeKeys.images(projectId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/projects/{project_id}/assets", { params: { path: { project_id: projectId }, query: { kind: "image", limit: 100 } } }))).items,
  });
}

export function useStartVisual(campaignId: string) {
  return useMutation({
    mutationFn: (body: VisualRequest) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/remakes/visual", { params: { path: { campaign_id: campaignId } }, body })),
  });
}

export function useStartSound(campaignId: string) {
  return useMutation({
    mutationFn: (body: SoundRequest) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/remakes/sound", { params: { path: { campaign_id: campaignId } }, body })),
  });
}

/** Poll a started remake run; when it finishes, refresh the remake list and the version tree once. */
export function useRemakeRun(campaignId: string, runId: string | null) {
  const client = useQueryClient();
  const run = useRun(runId);
  const status = run.data?.status;
  const done = status === "completed" || status === "partial" || status === "failed" || status === "cancelled";
  useQuery({
    queryKey: ["remake", "settled", runId, status],
    enabled: Boolean(runId) && done,
    staleTime: Infinity,
    queryFn: async () => {
      await client.invalidateQueries({ queryKey: remakeKeys.list(campaignId) });
      await client.invalidateQueries({ queryKey: remakeKeys.versions(campaignId) });
      return true;
    },
  });
  return run;
}
