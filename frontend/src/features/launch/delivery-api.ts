"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import createClient from "openapi-fetch";

import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";
import { env } from "@/lib/env";

type S = components["schemas"];

export type ReviewLink = S["ReviewLinkSummary"];
export type ReviewLinkCreated = S["ReviewLinkCreated"];
export type ReviewLinkCreate = S["ReviewLinkCreate"];
export type ReviewResponse = S["ReviewResponseView"];
export type ReviewDecision = S["ReviewSubmit"]["decision"];
export type ReviewPageData = S["ReviewPage"];
export type ReviewItemView = S["ReviewItemView"];
export type ReviewReceipt = S["ReviewReceipt"];
export type RegionPlan = S["RegionPlan"];
export type RegionPlanEntry = S["RegionPlanEntry"];
export type PlanCheck = S["PlanCheck"];
export type PlanEvent = S["PlanEvent"];
export type AssetPackPreview = S["AssetPackPreview"];
export type AssetPackManifest = S["AssetPackManifest"];
export type AssetPackSummary = S["AssetPackSummary"];
export type AssetPackCreated = S["AssetPackCreated"];
export type PackFile = S["PackFile"];

const root = (campaignId: string) => ["launch", campaignId, "delivery"] as const;
export const deliveryKeys = {
  links: (c: string) => [...root(c), "links"] as const,
  responses: (c: string) => [...root(c), "responses"] as const,
  plan: (c: string) => [...root(c), "plan"] as const,
  preview: (c: string, region: string) => [...root(c), "preview", region] as const,
  packs: (c: string) => [...root(c), "packs"] as const,
};

const path = (campaign_id: string) => ({ params: { path: { campaign_id } } });

// --- Review Links: the owner's side --------------------------------------------------------------------------------------------

export function useReviewLinks(campaignId: string) {
  return useQuery({
    queryKey: deliveryKeys.links(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/review-links", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } })),
  });
}

export function useReviewResponses(campaignId: string) {
  return useQuery({
    queryKey: deliveryKeys.responses(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/review-responses", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } })),
  });
}

export function useCreateReviewLink(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewLinkCreate) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/review-links", { ...path(campaignId), body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: deliveryKeys.links(campaignId) }),
  });
}

export function useRevokeReviewLink(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => unwrap(api.POST("/api/v1/review-links/{link_id}/revoke", { params: { path: { link_id: linkId } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: deliveryKeys.links(campaignId) });
      void queryClient.invalidateQueries({ queryKey: deliveryKeys.plan(campaignId) });
    },
  });
}

// --- Region Plan --------------------------------------------------------------------------------------------------------------------

export function useRegionPlan(campaignId: string) {
  return useQuery({
    queryKey: deliveryKeys.plan(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/region-plan", path(campaignId))),
  });
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Download the plan through the signed-in request. The server names the file (Content-Disposition). */
export async function downloadRegionPlan(campaignId: string, format: "markdown" | "pdf") {
  let response: Response | undefined;
  const blob = await unwrap(
    api
      .GET("/api/v1/campaigns/{campaign_id}/region-plan/export", { params: { path: { campaign_id: campaignId }, query: { format } }, parseAs: "blob" })
      .then((result) => {
        response = result.response;
        return result;
      }),
  );
  const named = /filename="([^"]+)"/.exec(response?.headers.get("content-disposition") ?? "")?.[1];
  saveBlob(blob as Blob, named ?? `omnicult-region-plan.${format === "pdf" ? "pdf" : "md"}`);
}

// --- Asset Pack ---------------------------------------------------------------------------------------------------------------------

export function useAssetPackPreview(campaignId: string, regionCode: string) {
  return useQuery({
    queryKey: deliveryKeys.preview(campaignId, regionCode),
    enabled: Boolean(regionCode),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/asset-packs/preview", { params: { path: { campaign_id: campaignId }, query: { region_code: regionCode } } })),
  });
}

export function useAssetPacks(campaignId: string) {
  return useQuery({
    queryKey: deliveryKeys.packs(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/asset-packs", { params: { path: { campaign_id: campaignId }, query: { limit: 20 } } })),
  });
}

export function useCreateAssetPack(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { region_code: string; version_id?: string | null }) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/asset-packs", { ...path(campaignId), body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: deliveryKeys.packs(campaignId) }),
  });
}

/** `download_url` is an API path; make it absolute against the configured API host. */
export const absoluteDownloadUrl = (value: string) => (/^https?:\/\//.test(value) ? value : `${env.apiBaseUrl.replace(/\/$/, "")}${value}`);

// --- the reviewer's side (no account) ---------------------------------------------------------------------------------------

/**
 * A client with no sign-in middleware: the review secret is the only credential and goes in the Authorization header as
 * `Review <secret>`, never in a URL. A signed-in owner who opens a link sees exactly what the reviewer sees.
 */
const reviewApi = createClient<paths>({ baseUrl: env.apiBaseUrl });
const header = (secret: string) => ({ Authorization: `Review ${secret}` });

export function useReviewPage(secret: string) {
  return useQuery({
    queryKey: ["review", "page", secret],
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: () => unwrap(reviewApi.GET("/api/v1/review", { params: { header: header(secret) } })),
  });
}

export function useSubmitReview(secret: string) {
  return useMutation({
    mutationFn: (body: S["ReviewSubmit"]) => unwrap(reviewApi.POST("/api/v1/review/responses", { params: { header: header(secret) }, body })),
  });
}

/** One creative file as an object URL. The request carries the secret in a header, so the file never needs it in a URL. */
export async function fetchReviewCreative(secret: string, creativeId: string): Promise<string> {
  let blob: unknown;
  try {
    blob = await unwrap(reviewApi.GET("/api/v1/review/creatives/{creative_id}", { params: { path: { creative_id: creativeId }, header: header(secret) }, parseAs: "blob" }));
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, "NETWORK_ERROR", "Could not load the file.");
  }
  return URL.createObjectURL(blob as Blob);
}
