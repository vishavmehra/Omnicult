"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type LensAtlas = S["LensAtlas"];
export type LensAtlasState = S["LensAtlasState"];
export type LensStateProfile = S["LensStateProfile"];
export type LensProfileSection = S["LensProfileSection"];
export type LensCompare = S["LensCompare"];
export type LensCompareItem = S["LensCompareItem"];
export type LensCalendar = S["LensCalendar"];
export type LensDatedMoment = S["LensDatedMoment"];
export type LensTimedMoment = S["LensTimedMoment"];
export type LensLanguageMap = S["LensLanguageMap"];
export type LensLanguageRegion = S["LensLanguageRegion"];
export type LensLanguageEntry = S["LensLanguageEntry"];
export type LensBuildView = S["LensBuildView"];
export type LensBuildRequest = S["LensBuildRequest"];
export type LensSourceSummary = S["LensSourceSummary"];
export type ClaimView = S["ClaimView"];
export type Conflict = S["Conflict"];
export type DataMode = S["LensAtlas"]["mode"];
export type StateFacts = S["StateFacts"];
export type StateFact = S["StateFact"];
export type StateFactGroup = S["StateFactGroup"];
export type LensStateData = S["LensStateData"];
export type LensFigure = S["LensFigure"];
export type LensDataSource = S["LensDataSource"];
export type LensDataRow = S["LensDataRow"];
export type LensCalendarEntry = S["LensCalendarEntry"];
export type LensTypicalMoment = S["LensTypicalMoment"];
export type LensAutoBuild = S["LensAutoBuild"];
export type LensAutoBuildRegion = S["LensAutoBuildRegion"];

export const lensKeys = {
  all: (campaignId: string) => ["lens", campaignId] as const,
  atlas: (campaignId: string) => ["lens", campaignId, "atlas"] as const,
  profile: (campaignId: string, region: string) => ["lens", campaignId, "profile", region] as const,
  compare: (campaignId: string, regions: string[]) => ["lens", campaignId, "compare", regions.join(",")] as const,
  calendar: (campaignId: string, region: string, year: number | null, from: string | null, to: string | null) =>
    ["lens", campaignId, "calendar", region, year, from, to] as const,
  stateFacts: (campaignId: string, region: string) => ["lens", campaignId, "state-facts", region] as const,
  languageMap: (campaignId: string) => ["lens", campaignId, "language-map"] as const,
  autoBuild: (campaignId: string) => ["lens", campaignId, "auto-build"] as const,
  claim: (workspaceId: string, claimId: string) => ["lens", "claim", workspaceId, claimId] as const,
};

const base = (campaignId: string) => ({ campaign_id: campaignId });

export function useAtlas(campaignId: string) {
  return useQuery({
    queryKey: lensKeys.atlas(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/atlas", { params: { path: base(campaignId) } })),
  });
}

export function useStateProfile(campaignId: string, region: string | null) {
  return useQuery({
    queryKey: lensKeys.profile(campaignId, region ?? ""),
    enabled: Boolean(region),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/regions/{region_code}/profile", { params: { path: { ...base(campaignId), region_code: region! } } })),
  });
}

export function useStateFacts(campaignId: string, region: string | null) {
  return useQuery({
    queryKey: lensKeys.stateFacts(campaignId, region ?? ""),
    enabled: Boolean(region),
    staleTime: 10 * 60_000, // the figures are annual or quarterly: one read per visit is plenty
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/regions/{region_code}/state-facts", { params: { path: { ...base(campaignId), region_code: region! } } })),
  });
}

export function useCompare(campaignId: string, regions: string[]) {
  return useQuery({
    queryKey: lensKeys.compare(campaignId, regions),
    enabled: regions.length >= 2 && regions.length <= 4,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/compare", { params: { path: base(campaignId), query: { region_code: regions } } })),
  });
}

export function useCalendar(campaignId: string, region: string | null, year: number | null, from: string | null, to: string | null) {
  const window = from && to && from <= to ? { window_from: from, window_to: to } : {};
  return useQuery({
    queryKey: lensKeys.calendar(campaignId, region ?? "", year, window.window_from ?? null, window.window_to ?? null),
    enabled: Boolean(region),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/lens/regions/{region_code}/calendar", {
          params: { path: { ...base(campaignId), region_code: region! }, query: { ...(year ? { year } : {}), ...window } },
        }),
      ),
  });
}

export function useLanguageMap(campaignId: string) {
  return useQuery({
    queryKey: lensKeys.languageMap(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/language-map", { params: { path: base(campaignId) } })),
  });
}

/**
 * The campaign's states, built in the background. Opening Lens asks the server once to queue every campaign state that has no
 * completed build (live campaigns, owner or editor); while any is queued or building the status is polled, and every Lens read
 * is refetched as each one lands.
 */
export function useAutoBuild(campaignId: string) {
  const qc = useQueryClient();
  const start = useQuery({
    queryKey: [...lensKeys.autoBuild(campaignId), "start"],
    staleTime: Infinity,
    retry: false,
    queryFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/lens/auto-build", { params: { path: base(campaignId) } })),
  });
  const running = start.data?.running ?? false;
  const status = useQuery({
    queryKey: lensKeys.autoBuild(campaignId),
    enabled: start.isSuccess && running,
    refetchInterval: (q) => (q.state.data?.running === false ? false : 3000),
    queryFn: async () => {
      const next = await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lens/auto-build", { params: { path: base(campaignId) } }));
      const before = qc.getQueryData<LensAutoBuild>(lensKeys.autoBuild(campaignId)) ?? start.data;
      const landed = next.regions.some((r) => r.state === "built" && before?.regions.find((b) => b.region_code === r.region_code)?.state !== "built");
      if (landed) void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "lens" && q.queryKey[1] === campaignId && q.queryKey[2] !== "auto-build" });
      return next;
    },
  });
  return status.data ?? start.data;
}

/** One claim with its sources, for the evidence drawer opened from a comparison cell. */
export function useClaim(workspaceId: string, claimId: string | null) {
  return useQuery({
    queryKey: lensKeys.claim(workspaceId, claimId ?? ""),
    enabled: Boolean(claimId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/workspaces/{workspace_id}/claims/{claim_id}", { params: { path: { workspace_id: workspaceId, claim_id: claimId! } } })),
  });
}

/** Build (or refresh) state profiles. Every Lens read is refetched afterwards, since a build changes all of them. */
export function useBuild(campaignId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LensBuildRequest) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/lens/builds", { params: { path: base(campaignId) }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: lensKeys.all(campaignId) }),
  });
}

export function useResolveConflict(campaignId: string, workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { conflictId: string; decision: "accept" | "switch" | "request_review" }) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/conflicts/{conflict_id}/resolve", {
          params: { path: { workspace_id: workspaceId, conflict_id: v.conflictId } },
          body: { decision: v.decision },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: lensKeys.all(campaignId) }),
  });
}
