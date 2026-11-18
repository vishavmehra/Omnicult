"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import type { FatigueQuery, PvaMetric } from "./logic";

type S = components["schemas"];

const root = (campaignId: string) => ["pulse-t3", campaignId] as const;
const path = (campaignId: string) => ({ path: { campaign_id: campaignId } });
/** The sample dataset is a 409 until it is loaded, and a 409 does not get better by retrying. */
const noRetry = { retry: false } as const;

// ---------------------------------------------------------------- Predicted vs Actual

export function usePredictedActual(campaignId: string, metric: PvaMetric) {
  return useQuery({
    queryKey: [...root(campaignId), "pva", metric],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/predicted-actual", { params: { ...path(campaignId), query: { metric } } })),
    ...noRetry,
  });
}

export function useVersionLinks(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "links"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/predicted-actual/links", { params: path(campaignId) })),
    ...noRetry,
  });
}

export function useSetVersionLink(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: S["PvaLinkSet"]) =>
      unwrap(api.PUT("/api/v1/campaigns/{campaign_id}/pulse/predicted-actual/links", { params: path(campaignId), body })),
    onSuccess: (board) => {
      queryClient.setQueryData([...root(campaignId), "links"], board);
      void queryClient.invalidateQueries({ queryKey: [...root(campaignId), "pva"] });
      void queryClient.invalidateQueries({ queryKey: [...root(campaignId), "snapshots"] });
    },
  });
}

export function useSnapshots(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "snapshots"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/predicted-actual/snapshots", { params: path(campaignId) })),
    ...noRetry,
  });
}

export function useSaveSnapshot(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (metric: PvaMetric) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/predicted-actual/snapshots", { params: path(campaignId), body: { metric } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: [...root(campaignId), "snapshots"] }),
  });
}

// ---------------------------------------------------------------- Alerts

export function useAlertRules(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "rules"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/alert-rules", { params: path(campaignId) })),
  });
}

export function useAlertInbox(campaignId: string) {
  return useQuery({
    queryKey: [...root(campaignId), "inbox"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/alert-inbox", { params: path(campaignId) })),
    ...noRetry,
  });
}

/** Rules and the inbox read each other's numbers (open alerts per rule), so a change to either refreshes both. */
function useRefreshAlerts(campaignId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: [...root(campaignId), "rules"] });
    void queryClient.invalidateQueries({ queryKey: [...root(campaignId), "inbox"] });
  };
}

export function useEvaluateAlerts(campaignId: string) {
  const refresh = useRefreshAlerts(campaignId);
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/alert-inbox/evaluate", { params: path(campaignId) })),
    onSuccess: refresh,
  });
}

/** Saving, changing or removing a rule evaluates straight away, so the inbox shows what the rule does now. */
export function useSaveRule(campaignId: string) {
  const refresh = useRefreshAlerts(campaignId);
  const evaluate = useEvaluateAlerts(campaignId);
  return useMutation({
    mutationFn: (v: { id: string | null; create: S["AlertRuleCreate"]; update: S["AlertRuleUpdate"] }) =>
      v.id === null
        ? unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/alert-rules", { params: path(campaignId), body: v.create }))
        : unwrap(api.PATCH("/api/v1/campaigns/{campaign_id}/pulse/alert-rules/{rule_id}", { params: { path: { campaign_id: campaignId, rule_id: v.id } }, body: v.update })),
    onSuccess: () => {
      refresh();
      evaluate.mutate();
    },
  });
}

export function useDeleteRule(campaignId: string) {
  const refresh = useRefreshAlerts(campaignId);
  return useMutation({
    mutationFn: (ruleId: string) =>
      unwrap(api.DELETE("/api/v1/campaigns/{campaign_id}/pulse/alert-rules/{rule_id}", { params: { path: { campaign_id: campaignId, rule_id: ruleId } } })),
    onSuccess: refresh,
  });
}

export function useDefaultRules(campaignId: string) {
  const refresh = useRefreshAlerts(campaignId);
  const evaluate = useEvaluateAlerts(campaignId);
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/alert-rules/defaults", { params: path(campaignId) })),
    onSuccess: () => {
      refresh();
      evaluate.mutate();
    },
  });
}

export function useTransitionAlert(campaignId: string) {
  const refresh = useRefreshAlerts(campaignId);
  return useMutation({
    mutationFn: (v: { alertId: string; action: S["AlertTransition"]["action"]; note: string | null }) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/pulse/alert-inbox/{alert_id}/transition", {
          params: { path: { campaign_id: campaignId, alert_id: v.alertId } },
          body: { action: v.action, note: v.note },
        }),
      ),
    onSuccess: refresh,
  });
}

// ---------------------------------------------------------------- Fatigue Watch

export function useFatigue(campaignId: string, q: FatigueQuery | null) {
  return useQuery({
    queryKey: [...root(campaignId), "fatigue", q],
    enabled: q !== null,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/fatigue", { params: { ...path(campaignId), query: q ?? undefined } })),
    ...noRetry,
  });
}
