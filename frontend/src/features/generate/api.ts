"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";

import { newKey } from "@/features/lab/labels";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useRun } from "@/lib/api/runs";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type GenerateCapabilities = S["GenerateCapabilities"];
export type GeneratorInfo = S["GeneratorInfo"];
export type GenerateItem = S["GenerateItem"];
export type GenerateAssetRef = S["GenerateAssetRef"];
export type GenerateKind = GenerateItem["kind"];
export type ImageRequest = S["GenerateImageRequest"];
export type VoiceRequest = S["GenerateVoiceRequest"];
export type JingleRequest = S["GenerateJingleRequest"];
export type ImageFormat = ImageRequest["format"];
export type Pace = VoiceRequest["pace"];
export type ProjectAsset = S["Asset"];
export type VersionNode = S["VersionNode"];
export type VersionSummary = S["VersionSummary"];
export type Run = S["Run"];

export const generateKeys = {
  caps: (campaignId: string) => ["generate", "capabilities", campaignId] as const,
  items: (campaignId: string) => ["generate", "items", campaignId] as const,
  versions: (campaignId: string) => ["generate", "versions", campaignId] as const,
  version: (campaignId: string, versionId: string) => ["generate", "version", campaignId, versionId] as const,
  images: (projectId: string) => ["generate", "images", projectId] as const,
};

const path = (campaignId: string) => ({ params: { path: { campaign_id: campaignId } } });

export function useGenerateCapabilities(campaignId: string) {
  return useQuery({
    queryKey: generateKeys.caps(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/generate/capabilities", path(campaignId))),
  });
}

/** Finished generate runs of the campaign, newest first. Failed runs are included: a provider error is never hidden. */
export function useGenerateItems(campaignId: string) {
  return useQuery({
    queryKey: generateKeys.items(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/generate/items", { params: { path: { campaign_id: campaignId }, query: { limit: 60 } } }))).items,
  });
}

/**
 * Starts a paid run (202). One Idempotency-Key per distinct request body: a retry of the same body after a network error
 * returns the run the server already made, while a deliberate second run (the key is cleared on success) starts a new one.
 */
function useStarter<B>(post: (body: B, headers: { "Idempotency-Key": string }) => Promise<{ run_id: string }>) {
  const pending = useRef<{ sig: string; key: string } | null>(null);
  const busy = useRef(false); // set at once: isPending only turns true after a render, and a held Enter repeats faster than that
  const mutation = useMutation({
    mutationFn: async (body: B) => {
      const sig = JSON.stringify(body);
      if (pending.current?.sig !== sig) pending.current = { sig, key: newKey() };
      return post(body, { "Idempotency-Key": pending.current.key });
    },
    onSuccess: () => {
      pending.current = null;
    },
    onSettled: () => {
      busy.current = false;
    },
  });
  const { mutate } = mutation;
  const start = useCallback(
    (body: B, options?: Parameters<typeof mutate>[1]) => {
      if (busy.current) return; // a repeat of a submit still in flight is dropped, not queued
      busy.current = true;
      mutate(body, options);
    },
    [mutate],
  );
  return { ...mutation, mutate: start };
}

export function useStartImage(campaignId: string) {
  return useStarter<ImageRequest>((body, headers) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/generate/image", { ...path(campaignId), body, headers })));
}

export function useStartVoice(campaignId: string) {
  return useStarter<VoiceRequest>((body, headers) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/generate/voice", { ...path(campaignId), body, headers })));
}

export function useStartJingle(campaignId: string) {
  return useStarter<JingleRequest>((body, headers) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/generate/jingle", { ...path(campaignId), body, headers })));
}

/** Poll a started generate run; once it has finished, refresh the gallery (and the version tree) once. */
export function useGenerateRun(campaignId: string, runId: string | null) {
  const client = useQueryClient();
  const run = useRun(runId);
  const status = run.data?.status;
  const done = status === "completed" || status === "partial" || status === "failed" || status === "cancelled";
  useQuery({
    queryKey: ["generate", "settled", runId, status],
    enabled: Boolean(runId) && done,
    staleTime: Infinity,
    queryFn: async () => {
      await client.invalidateQueries({ queryKey: generateKeys.items(campaignId) });
      return true;
    },
  });
  return run;
}

/** Add an output to a Studio version as a new element (a new version; the source is untouched). */
export function useUseInStudio(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, versionId }: { runId: string; versionId: string | null }) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/generate/items/{run_id}/use-in-studio", {
          params: { path: { campaign_id: campaignId, run_id: runId } },
          body: { version_id: versionId },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: generateKeys.items(campaignId) });
      await client.invalidateQueries({ queryKey: generateKeys.versions(campaignId) });
    },
  });
}

/** Every version node of the campaign, oldest first. */
export function useVersionList(campaignId: string) {
  return useQuery({
    queryKey: generateKeys.versions(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } }))).items,
  });
}

/** One version with its elements, for pulling lines of copy into the voice-over. */
export function useVersion(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: generateKeys.version(campaignId, versionId ?? "none"),
    enabled: Boolean(versionId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}", { params: { path: { campaign_id: campaignId, version_id: versionId! } } })),
  });
}

/** The project's uploaded images (generated and other derived files are hidden by the API). */
export function useProjectImages(projectId: string) {
  return useQuery({
    queryKey: generateKeys.images(projectId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/projects/{project_id}/assets", { params: { path: { project_id: projectId }, query: { kind: "image", limit: 24 } } }))).items,
  });
}

/** The brief's target regions, to preselect a region. */
export function useBriefRegions(campaignId: string) {
  return useQuery({
    queryKey: ["generate", "brief-regions", campaignId],
    queryFn: async () => {
      const brief = await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/brief", path(campaignId)));
      const content = brief.content;
      return [...(content.regions.targets ?? []), ...(content.regions.origin ? [content.regions.origin] : [])];
    },
  });
}
