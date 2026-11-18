"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { newKey } from "../labels";
import { isActive, type RunStatus } from "../types";

type S = components["schemas"];
export type MessageCheckResult = S["MessageCheckResult"];
export type MessageCheckCreate = S["MessageCheckCreate"];
export type MessageCheckRegion = S["MessageCheckRegion"];
export type MessageCheckRates = S["MessageCheckRates"];
export type MessageCheckParticipant = S["MessageCheckParticipant"];
export type LabSessionDefaults = S["LabSessionDefaults"];

const keys = {
  defaults: (c: string) => ["lab", c, "session-defaults"] as const,
  runs: (c: string) => ["lab", c, "runs", "message_check"] as const,
  result: (c: string, id: string | null | undefined) => ["lab", c, "result", "message_check", id] as const,
};

/** The brief's primary message and its key points (split by the server), and the limits the form must respect. */
export function useSessionDefaults(campaignId: string) {
  return useQuery({
    queryKey: keys.defaults(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lab-session-defaults", { params: { path: { campaign_id: campaignId } } })),
    staleTime: 60_000,
  });
}

export function useMessageChecks(campaignId: string) {
  return useQuery({
    queryKey: keys.runs(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/message-checks", { params: { path: { campaign_id: campaignId }, query: { limit: 20 } } })),
    select: (page) => page.items,
    refetchInterval: (q) => (q.state.data?.items.some((r) => isActive(r.status)) ? 4000 : false),
  });
}

/** Poll every 1.5 s while the run is queued or running (the participants and marks arrive at the end), then stop. */
function pollEvery(status: RunStatus | undefined, failed: boolean) {
  if (failed) return false;
  return !status || isActive(status) ? 1500 : false;
}

export function useMessageCheck(campaignId: string, runId: string | null | undefined) {
  return useQuery<MessageCheckResult>({
    queryKey: keys.result(campaignId, runId),
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/message-checks/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => pollEvery(q.state.data?.status, q.state.status === "error"),
  });
}

/** One Idempotency-Key per distinct body: a retry after a network error returns the run the server already made. */
export function useStartMessageCheck(campaignId: string) {
  const qc = useQueryClient();
  const pending = useRef<{ sig: string; key: string } | null>(null);
  return useMutation({
    mutationFn: async (body: MessageCheckCreate) => {
      const sig = JSON.stringify(body);
      if (pending.current?.sig !== sig) pending.current = { sig, key: newKey() };
      return unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/message-checks", {
          params: { path: { campaign_id: campaignId } },
          body,
          headers: { "Idempotency-Key": pending.current.key },
        }),
      );
    },
    onSuccess: () => {
      pending.current = null;
      void qc.invalidateQueries({ queryKey: keys.runs(campaignId) });
    },
  });
}
