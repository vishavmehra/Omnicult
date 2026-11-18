"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import type { FitStrategy, ReviewDecision } from "./types";

/** Every Tier 3 query hangs under ["studio-t3", campaignId], so one invalidation refreshes the three panels after a write. */
export const t3Keys = {
  all: (campaignId: string) => ["studio-t3", campaignId] as const,
  formats: (campaignId: string) => ["studio-t3", campaignId, "formats"] as const,
  plans: (campaignId: string, creativeId: string | null, versionId: string | null) => ["studio-t3", campaignId, "plans", creativeId, versionId] as const,
  outputs: (campaignId: string) => ["studio-t3", campaignId, "outputs"] as const,
  script: (campaignId: string, versionId: string | null) => ["studio-t3", campaignId, "script", versionId] as const,
  checks: (campaignId: string, versionId: string | null) => ["studio-t3", campaignId, "checks", versionId] as const,
  check: (campaignId: string, checkId: string | null) => ["studio-t3", campaignId, "check", checkId] as const,
};

const path = (campaignId: string) => ({ params: { path: { campaign_id: campaignId } } });

// ---------- Format Fit ----------

export function useFormatCatalogue(campaignId: string) {
  return useQuery({
    queryKey: t3Keys.formats(campaignId),
    staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/format-fit/formats", path(campaignId))),
  });
}

/** Planning is a read (POST only because it takes a body): nothing is stored. */
export function useFormatPlans(campaignId: string, creativeId: string | null, versionId: string | null) {
  return useQuery({
    queryKey: t3Keys.plans(campaignId, creativeId, versionId),
    enabled: Boolean(creativeId && versionId),
    queryFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/format-fit/plans", { ...path(campaignId), body: { creative_id: creativeId!, version_id: versionId! } })),
  });
}

export function useFormatOutputs(campaignId: string) {
  return useQuery({
    queryKey: t3Keys.outputs(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/format-fit/outputs", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } })),
  });
}

export type ApplyVars = { creativeId: string; versionId: string; formatId: string; strategy: FitStrategy; background: string | null; acknowledge: boolean };

export function useApplyFormat(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: ApplyVars) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/format-fit/outputs", {
          ...path(campaignId),
          body: { creative_id: v.creativeId, version_id: v.versionId, format_id: v.formatId, strategy: v.strategy, background: v.background, acknowledge_issues: v.acknowledge },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: t3Keys.outputs(campaignId) });
      void client.invalidateQueries({ queryKey: ["xray", "uploads"] }); // the new asset is an upload of the project
    },
  });
}

// ---------- Script Check ----------

export function useScriptReport(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: t3Keys.script(campaignId, versionId),
    enabled: Boolean(versionId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}/script-check", { params: { path: { campaign_id: campaignId, version_id: versionId! } } })),
  });
}

// ---------- Claim Guard ----------

export function useClaimChecks(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: t3Keys.checks(campaignId, versionId),
    enabled: Boolean(versionId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/claim-guard/checks", { params: { path: { campaign_id: campaignId }, query: { version_id: versionId!, limit: 5 } } })),
  });
}

export function useClaimCheck(campaignId: string, checkId: string | null) {
  return useQuery({
    queryKey: t3Keys.check(campaignId, checkId),
    enabled: Boolean(checkId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/claim-guard/checks/{check_id}", { params: { path: { campaign_id: campaignId, check_id: checkId! } } })),
  });
}

export function useRunClaimCheck(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { versionId: string; model: boolean }) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/claim-guard/checks", { ...path(campaignId), body: { version_id: v.versionId, include_model_pass: v.model } })),
    onSuccess: () => client.invalidateQueries({ queryKey: t3Keys.all(campaignId) }),
  });
}

export function useReviewFinding(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { versionId: string; key: string; decision: ReviewDecision; note: string | null }) =>
      unwrap(api.PUT("/api/v1/campaigns/{campaign_id}/claim-guard/reviews", { ...path(campaignId), body: { version_id: v.versionId, finding_key: v.key, decision: v.decision, note: v.note } })),
    onSuccess: () => client.invalidateQueries({ queryKey: t3Keys.all(campaignId) }),
  });
}
