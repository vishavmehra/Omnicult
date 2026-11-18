"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type TrendRadar = S["LensTrendRadar"];
export type TrendRegion = S["LensTrendRegion"];
export type TrendItem = S["LensTrendItem"];
export type TrendEdition = S["LensTrendEdition"];
export type TrendMoment = S["LensTrendMoment"];
export type TrendDirection = TrendItem["direction"];
export type CategoryShelf = S["LensShelf"];
export type ShelfRegion = S["LensShelfRegion"];
export type ShelfEntity = S["LensShelfEntity"];
export type ShelfAttention = S["LensShelfAttention"];
export type SourceLink = S["LensSourceLink"];
export type LensMonth = S["LensMonth"];

const keys = {
  all: (campaignId: string) => ["lens-t3", campaignId] as const,
  radar: (campaignId: string, regions: string[]) => ["lens-t3", campaignId, "radar", regions.join(",")] as const,
  shelf: (campaignId: string, regions: string[], pack: string | null) => ["lens-t3", campaignId, "shelf", regions.join(","), pack ?? ""] as const,
};

const path = (campaignId: string) => ({ campaign_id: campaignId });

export function useTrendRadar(campaignId: string, regions: string[]) {
  return useQuery({
    queryKey: keys.radar(campaignId, regions),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/trend-radar", { params: { path: path(campaignId), query: regions.length ? { region_code: regions } : {} } })),
  });
}

/** Read the pageviews again. Every Trend Radar read is refetched afterwards. */
export function useRefreshRadar(campaignId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (regions: string[]) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/lens/trend-radar/refresh", { params: { path: path(campaignId) }, body: regions.length ? { region_codes: regions } : {} })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.all(campaignId) }),
  });
}

export function useCategoryShelf(campaignId: string, regions: string[], pack: string | null) {
  return useQuery({
    queryKey: keys.shelf(campaignId, regions, pack),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/lens/category-shelf", {
          params: { path: path(campaignId), query: { ...(regions.length ? { region_code: regions } : {}), ...(pack ? { pack_key: pack } : {}) } },
        }),
      ),
  });
}

export function useRefreshShelf(campaignId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { pack: string | null; regions: string[] }) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/lens/category-shelf/refresh", {
          params: { path: path(campaignId) },
          body: { ...(v.pack ? { pack_key: v.pack } : {}), ...(v.regions.length ? { region_codes: v.regions } : {}) },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.all(campaignId) }),
  });
}
