"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { newKey } from "../labels";
import { isActive } from "../types";

type S = components["schemas"];
export type FocusGroupResult = S["FocusGroupResult"];
export type FocusGroupCreate = S["FocusGroupCreate"];
export type FocusTurn = S["FocusGroupTurnView"];

const keys = {
  defaults: (c: string) => ["lab", c, "session-defaults"] as const,
  runs: (c: string) => ["lab", c, "runs", "focus_group"] as const,
  result: (c: string, id: string | null | undefined) => ["lab", c, "result", "focus_group", id] as const,
};

/** The default moderator guide and the server limits the setup form starts from. */
export function useFocusDefaults(campaignId: string) {
  return useQuery({
    queryKey: keys.defaults(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/lab-session-defaults", { params: { path: { campaign_id: campaignId } } })),
    staleTime: 60_000,
  });
}

/** Focus Group sessions of this campaign, newest first. Polls while one is queued or running. */
export function useFocusRuns(campaignId: string) {
  return useQuery({
    queryKey: keys.runs(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/focus-groups", { params: { path: { campaign_id: campaignId }, query: { limit: 20 } } })),
    select: (page) => page.items,
    refetchInterval: (q) => (q.state.data?.items.some((r) => isActive(r.status)) ? 4000 : false),
  });
}

/** One session, with its transcript so far. Polls every second while it runs (turns stream in), then stops. */
export function useFocusGroup(campaignId: string, runId: string | null | undefined) {
  return useQuery<FocusGroupResult>({
    queryKey: keys.result(campaignId, runId),
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/focus-groups/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => (q.state.status === "error" ? false : !q.state.data || isActive(q.state.data.status) ? 1000 : false),
  });
}

/** Starts a session (202). One Idempotency-Key per distinct body, so a retry after a network error returns the run already created. */
export function useStartFocusGroup(campaignId: string) {
  const qc = useQueryClient();
  const pending = useRef<{ sig: string; key: string } | null>(null);
  return useMutation({
    mutationFn: async (body: FocusGroupCreate) => {
      const sig = JSON.stringify(body);
      if (pending.current?.sig !== sig) pending.current = { sig, key: newKey() };
      return unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/focus-groups", {
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

/** Queues a question for the moderator to relay at the next turn boundary. */
export function useInterject(campaignId: string, runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/focus-groups/{run_id}/interjections", { params: { path: { campaign_id: campaignId, run_id: runId } }, body: { text } })),
    onSettled: () => void qc.invalidateQueries({ queryKey: keys.result(campaignId, runId) }),
  });
}
