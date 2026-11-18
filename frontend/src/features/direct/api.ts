"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { studioKeys } from "@/features/studio/api";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import type { DirectPlan } from "./types";

/** Hangs under the Studio's own key, so every Studio write and every plan applied here refresh the same screen. */
export const directKeys = {
  plans: (campaignId: string) => [...studioKeys.all(campaignId), "direct", "plans"] as const,
};

const path = (campaignId: string) => ({ params: { path: { campaign_id: campaignId } } });

export function useDirectPlans(campaignId: string) {
  return useQuery({
    queryKey: directKeys.plans(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/direct/plans", { params: { path: { campaign_id: campaignId }, query: { limit: 8 } } })),
  });
}

/** One model call: it plans and stores, it never changes the creative. */
export function useCreatePlan(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { versionId: string; instruction: string; source: "typed" | "voice"; transcript: string | null }) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/direct/plans", {
          ...path(campaignId),
          body: { version_id: vars.versionId, instruction: vars.instruction, source: vars.source, transcript: vars.transcript },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: directKeys.plans(campaignId) }),
  });
}

/** Runs only the confirmed steps. Applied steps make versions and locks, so the whole Studio tree of queries is refreshed. */
export function useApplyPlan(campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { planId: string; stepIds: string[] }) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/direct/plans/{plan_id}/apply", {
          params: { path: { campaign_id: campaignId, plan_id: vars.planId } },
          body: { step_ids: vars.stepIds },
        }),
      ),
    onSettled: () => client.invalidateQueries({ queryKey: studioKeys.all(campaignId) }),
  });
}

/** The recording goes up once, is transcribed and is not kept. The person corrects the text before it is planned. */
export function useTranscribe(campaignId: string) {
  return useMutation({
    mutationFn: (vars: { clip: Blob; filename: string; language: string }) => {
      const form = new FormData();
      form.append("file", vars.clip, vars.filename);
      if (vars.language) form.append("language", vars.language);
      // openapi-fetch sends FormData as-is, so the browser sets the multipart boundary.
      return unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/direct/transcribe", {
          ...path(campaignId),
          body: form as unknown as components["schemas"]["Body_transcribe_instruction"],
        }),
      );
    },
  });
}

export type { DirectPlan };
