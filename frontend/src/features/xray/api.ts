"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { getAccessToken } from "@/lib/auth/token";
import { env } from "@/lib/env";

type S = components["schemas"];

export type Creative = S["Creative"];
export type CreativeSummary = S["CreativeSummary"];
export type Scene = S["Scene"];
export type Asset = S["Asset"];
export type AssetStatus = S["AssetStatus"];
export type MediaCapabilities = S["MediaCapabilities"];
export type RenderTextRequest = S["RenderTextRequest"];
export type TranscriptSegment = S["TranscriptSegment"];
export type Provenance = Scene["provenance"][string];
export type AssetKind = Asset["kind"];

export const xrayKeys = {
  all: ["xray"] as const,
  creatives: (campaignId: string) => ["xray", "creatives", campaignId] as const,
  creative: (id: string) => ["xray", "creative", id] as const,
  scenes: (id: string, runId: string | null) => ["xray", "scenes", id, runId] as const,
  uploads: (projectId: string) => ["xray", "uploads", projectId] as const,
  assetStatus: (id: string) => ["xray", "asset-status", id] as const,
};

const ACTIVE = ["queued", "running"];
export const isActive = (status: string | null | undefined) => Boolean(status && ACTIVE.includes(status));

export function useCreatives(campaignId: string) {
  return useQuery({
    queryKey: xrayKeys.creatives(campaignId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/creatives", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } }))).items,
    refetchInterval: (q) => (q.state.data?.some((c) => isActive(c.status)) ? 3000 : false),
  });
}

export function useCreative(id: string | null) {
  return useQuery({
    queryKey: xrayKeys.creative(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/v1/creatives/{creative_id}", { params: { path: { creative_id: id! } } })),
    refetchInterval: (q) => (isActive(q.state.data?.status) ? 2500 : false),
  });
}

/** Scenes of the creative's current run, in time order. Keyed by run so a new run replaces them. */
export function useScenes(creativeId: string, runId: string | null) {
  return useQuery({
    queryKey: xrayKeys.scenes(creativeId, runId),
    enabled: Boolean(runId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/creatives/{creative_id}/scenes", { params: { path: { creative_id: creativeId }, query: { limit: 100 } } }))).items,
  });
}

/** Uploads of the project that are not derived files, newest first (the caller drops those already analysed). */
export function useUploads(projectId: string) {
  return useQuery({
    queryKey: xrayKeys.uploads(projectId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/projects/{project_id}/assets", { params: { path: { project_id: projectId }, query: { limit: 50 } } }))).items,
  });
}

/** Processing status of an uploaded file; polls until ffmpeg work has settled. */
export function useAssetStatus(assetId: string | null) {
  return useQuery({
    queryKey: xrayKeys.assetStatus(assetId ?? ""),
    enabled: Boolean(assetId),
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}/status", { params: { path: { asset_id: assetId! } } })),
    refetchInterval: (q) => (q.state.data && q.state.data.processing_status === "processing" ? 2000 : false),
  });
}

export function useMediaCapabilities() {
  return useQuery({
    queryKey: ["xray", "capabilities"],
    staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/media/capabilities")),
  });
}

export function useRegions() {
  return useQuery({
    queryKey: ["xray", "regions"],
    staleTime: 30 * 60_000,
    queryFn: async () => (await unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: "IN", limit: 100 } } }))).items,
  });
}

export type UploadInput = { file: File; kind: AssetKind; rightsConfirmed: boolean; sidecar: File | null };

export function useUploadAsset(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, kind, rightsConfirmed, sidecar }: UploadInput) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      form.append("rights_confirmed", rightsConfirmed ? "true" : "false");
      if (sidecar) form.append("sidecar", sidecar);
      // openapi-fetch sends FormData as-is, so the browser sets the multipart boundary.
      return unwrap(api.POST("/api/v1/projects/{project_id}/assets", { params: { path: { project_id: projectId } }, body: form as unknown as S["Body_upload_asset"] }));
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: xrayKeys.uploads(projectId) }),
  });
}

export type RunInput = { assetId: string; label: string | null; language: string | null; regionCode: string | null };

/**
 * Starts Creative X-Ray. Each click carries its own Idempotency-Key, so a double click replays instead of running twice.
 * The API's CORS list must allow that header; where it does not (the browser refuses the preflight, which reads as a
 * network error) the request is sent once more without it. A refused preflight means the first request never left.
 */
export function useStartXRay(campaignId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, label, language, regionCode }: RunInput) => {
      const post = (headers?: Record<string, string>) =>
        unwrap(
          api.POST("/api/v1/campaigns/{campaign_id}/creative-xrays", {
            params: { path: { campaign_id: campaignId } },
            headers,
            body: { asset_id: assetId, label: label || null, language: language || null, region_code: regionCode || null },
          }),
        );
      return post({ "Idempotency-Key": crypto.randomUUID() }).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 0) return post();
        throw error;
      });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: xrayKeys.all }),
  });
}

/** Bytes of an asset. The content endpoint needs the API token, so it cannot be an <img src>. Cached for the session. */
export function useBlob(path: string | null | undefined) {
  return useQuery({
    queryKey: ["xray-blob", path],
    enabled: Boolean(path),
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    retry: 1,
    queryFn: async () => {
      const token = await getAccessToken();
      const res = await fetch(`${env.apiBaseUrl}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
      return res.blob();
    },
  });
}

/** An object URL for a blob, revoked when the blob changes or the component unmounts. */
export function useObjectUrl(blob: Blob | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const next = blob ? URL.createObjectURL(blob) : null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- an object URL is an external resource owned by this effect
    setUrl(next);
    return () => {
      if (next) URL.revokeObjectURL(next);
    };
  }, [blob]);
  return url;
}

export type TextPreview = { url: string; shaping: string; fits: boolean[]; overlapsLocked: boolean[]; lockedRestored: number };

const flags = (value: string | null) => (value ? value.split(",").map((f) => f === "true") : []);

/** Renders regional text onto a keyframe in code. The report comes from the X-Omnicult-* response headers. */
export async function renderTextPreview(projectId: string, body: RenderTextRequest): Promise<TextPreview> {
  let result;
  try {
    result = await api.POST("/api/v1/projects/{project_id}/media/render-text", { params: { path: { project_id: projectId } }, body, parseAs: "blob" });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the Omnicult API.");
  }
  if (!result.response.ok) await unwrap(Promise.resolve(result)); // throws the API's error envelope
  const h = result.response.headers;
  return {
    url: URL.createObjectURL(result.data as Blob),
    shaping: h.get("X-Omnicult-Shaping") ?? "unknown",
    fits: flags(h.get("X-Omnicult-Text-Fit")),
    overlapsLocked: flags(h.get("X-Omnicult-Overlaps-Locked")),
    lockedRestored: Number(h.get("X-Omnicult-Locked-Restored") ?? 0),
  };
}
