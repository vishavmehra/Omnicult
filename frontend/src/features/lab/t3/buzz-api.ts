"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { newKey } from "../labels";
import { isActive, type RunStatus } from "../types";

type S = components["schemas"];

export type BuzzCreate = S["BuzzCreate"];
export type BuzzResult = S["BuzzResult"];
export type BuzzAct = S["BuzzActView"];
export type BuzzSummary = S["BuzzSummary"];
export type BuzzCohort = S["BuzzCohortRow"];
export type SessionDefaults = S["LabSessionDefaults"];

export const buzzKeys = {
  defaults: (c: string) => ["lab", c, "session-defaults"] as const,
  runs: (c: string) => ["lab", c, "runs", "buzz_sim"] as const,
  result: (c: string, id: string | null | undefined) => ["lab", c, "result", "buzz_sim", id] as const,
};

/** The platforms and limits the form starts from. Shared by the three session tabs, so the key is the same. */
export function useSessionDefaults(campaignId: string) {
  return useQuery<SessionDefaults>({
    queryKey: buzzKeys.defaults(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lab-session-defaults", { params: { path: { campaign_id: campaignId } } })),
    staleTime: 60_000,
  });
}

/** Simulations of this campaign, newest first. Polls while one is queued or running. */
export function useBuzzRuns(campaignId: string) {
  return useQuery({
    queryKey: buzzKeys.runs(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/buzz-simulations", { params: { path: { campaign_id: campaignId }, query: { limit: 20 } } })),
    select: (page) => page.items,
    refetchInterval: (q) => (q.state.data?.items.some((r) => isActive(r.status)) ? 4000 : false),
  });
}

/** Every 1.5 s for the first 30 s of a run, then every 5 s; stops once it has finished or the request failed. Acts arrive round by round. */
function pollEvery(status: RunStatus | undefined, createdAt: string | undefined, failed: boolean) {
  if (failed) return false;
  if (!status) return 1500;
  if (!isActive(status)) return false;
  return createdAt && Date.now() - Date.parse(createdAt) < 30_000 ? 1500 : 5000;
}

export function useBuzz(campaignId: string, runId: string | null | undefined) {
  return useQuery<BuzzResult>({
    queryKey: buzzKeys.result(campaignId, runId),
    enabled: Boolean(runId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/buzz-simulations/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => pollEvery(q.state.data?.status, q.state.data?.created_at, q.state.status === "error"),
  });
}

/** One Idempotency-Key per distinct body: a retry after a network error returns the run the server already made; a deliberate second run starts a new one. */
export function useStartBuzz(campaignId: string) {
  const qc = useQueryClient();
  const pending = useRef<{ sig: string; key: string } | null>(null);
  return useMutation({
    mutationFn: async (body: BuzzCreate) => {
      const sig = JSON.stringify(body);
      if (pending.current?.sig !== sig) pending.current = { sig, key: newKey() };
      return unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/buzz-simulations", {
          params: { path: { campaign_id: campaignId } },
          body,
          headers: { "Idempotency-Key": pending.current.key },
        }),
      );
    },
    onSuccess: () => {
      pending.current = null;
      void qc.invalidateQueries({ queryKey: buzzKeys.runs(campaignId) });
    },
  });
}
