"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import type { GroupBy, Platform, Range, ThresholdQuery } from "./logic";

/** Filters every section below the filter row shares (dataviz rule: one row of filters, everything re-renders against it). */
export type Filters = { range: Range; platform: Platform | "all"; region: string };
export const ALL_REGIONS = "all";
export const DEFAULT_FILTERS: Filters = { range: { from: null, to: null }, platform: "all", region: ALL_REGIONS };

const root = (campaignId: string) => ["pulse", campaignId] as const;

/** The sample dataset is a 409 until it is loaded, and a 409 does not get better by retrying. */
const noRetry = { retry: false } as const;

function scope(f: Filters) {
  return {
    date_from: f.range.from,
    date_to: f.range.to,
    platform: f.platform === "all" ? null : f.platform,
    region: f.region === ALL_REGIONS ? null : f.region,
  };
}

const path = (campaignId: string) => ({ path: { campaign_id: campaignId } });

export function useDatasetStatus(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "status"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/sample-dataset", { params: path(campaignId) })),
    ...noRetry,
  });
}

export function useLoadSample(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/sample-dataset", { params: path(campaignId) })),
    onSuccess: (status) => {
      // Identical rows are written on every load, but the cache must not outlive the replacement.
      queryClient.setQueryData([...root(campaignId), "status"], status);
      void queryClient.invalidateQueries({ queryKey: root(campaignId) });
    },
  });
}

export function useMetricCatalogue(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "metrics"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/metrics", { params: path(campaignId) })),
    staleTime: 5 * 60_000,
  });
}

export function useConnections(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "connections"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/connections", { params: path(campaignId) })),
  });
}

export function usePredictedVsActual(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "predicted-vs-actual"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/predicted-vs-actual", { params: path(campaignId) })),
  });
}

export function useFreshness(campaignId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...root(campaignId), "freshness"],
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/freshness", { params: path(campaignId) })),
    ...noRetry,
  });
}

export function useSummary(campaignId: string, f: Filters, enabled: boolean) {
  return useQuery({
    queryKey: [...root(campaignId), "summary", f],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/summary", { params: { ...path(campaignId), query: scope(f) } })),
    ...noRetry,
  });
}

export function useTimeSeries(campaignId: string, f: Filters, opts: { metric: string; groupBy: GroupBy }, enabled: boolean) {
  return useQuery({
    queryKey: [...root(campaignId), "timeseries", f, opts],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/pulse/timeseries", {
          params: { ...path(campaignId), query: { ...scope(f), metric: [opts.metric], group_by: opts.groupBy } },
        }),
      ),
    ...noRetry,
  });
}

/** One metric for one region and version over the whole dataset: the series behind an alert. */
export function useAlertSeries(campaignId: string, s: { metric: string; region: string; version: string; from: string; to: string }, enabled: boolean) {
  return useQuery({
    queryKey: [...root(campaignId), "alert-series", s],
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/pulse/timeseries", {
          params: {
            ...path(campaignId),
            query: { metric: [s.metric], region: s.region, version: s.version, date_from: s.from, date_to: s.to, group_by: "none" },
          },
        }),
      ),
    ...noRetry,
  });
}

export function useVersionComparison(campaignId: string, f: Filters, baseline: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...root(campaignId), "compare", f, baseline],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/pulse/versions/compare", {
          params: { ...path(campaignId), query: { ...scope({ ...f, region: f.region }), baseline } },
        }),
      ),
    ...noRetry,
  });
}

export function useAlertPreview(campaignId: string, thresholds: ThresholdQuery | null) {
  return useQuery({
    queryKey: [...root(campaignId), "alerts", thresholds],
    enabled: thresholds !== null,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/alerts", { params: { ...path(campaignId), query: thresholds ?? undefined } })),
    ...noRetry,
  });
}
