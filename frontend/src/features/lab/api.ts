"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import { newKey } from "./labels";
import {
  isActive,
  type AdCodeIndex,
  type AudienceStudyCreate,
  type AskBody,
  type AudienceStudyResult,
  type FindingStatus,
  type PanelQuestion,
  type QuickReadCreate,
  type QuickReadResult,
  type RiskCheckCreate,
  type RiskCheckFinding,
  type RiskCheckResult,
  type RunKind,
  type RunStatus,
} from "./types";

/** Audience Lab runs live in `audience_runs`, not the generic run list, so each kind has its own list and result endpoints. */
export const labKeys = {
  runs: (c: string, kind: RunKind) => ["lab", c, "runs", kind] as const,
  result: (c: string, kind: RunKind, id: string | null | undefined) => ["lab", c, "result", kind, id] as const,
  participants: (c: string, run: string | null | undefined) => ["lab", c, "participants", run] as const,
  questions: (c: string, run: string | null | undefined, participant: string | null | undefined) => ["lab", c, "questions", run, participant ?? "all"] as const,
};

// ---------- reference ----------

export function useSamplingOptions() {
  return useQuery({
    queryKey: ["lab", "sampling-options"],
    queryFn: () => unwrap(api.GET("/api/v1/audience-lab/sampling-options")),
    staleTime: Infinity,
  });
}

/** The ASCI clause index: exact cited excerpts with their PDF page. Fetched once; findings quote from it. */
export function useAdCodeIndex() {
  return useQuery<AdCodeIndex>({
    queryKey: ["lab", "ad-codes"],
    queryFn: () => unwrap(api.GET("/api/v1/ad-codes")),
    staleTime: Infinity,
  });
}

// ---------- runs ----------

/** Runs of one kind, newest first. Polls while one is queued or running. */
export function useRuns(campaignId: string, kind: RunKind) {
  return useQuery({
    queryKey: labKeys.runs(campaignId, kind),
    queryFn: async () => {
      const params = { path: { campaign_id: campaignId }, query: { limit: 20 } };
      switch (kind) {
        case "quick_read":
          return unwrap(api.GET("/api/v1/campaigns/{campaign_id}/quick-reads", { params }));
        case "audience_study":
          return unwrap(api.GET("/api/v1/campaigns/{campaign_id}/audience-studies", { params }));
        case "risk_check":
          return unwrap(api.GET("/api/v1/campaigns/{campaign_id}/risk-checks", { params }));
      }
    },
    select: (page) => page.items,
    refetchInterval: (q) => (q.state.data?.items.some((r) => isActive(r.status)) ? 4000 : false),
  });
}

/** Poll every 1.5 s for the first 30 s of a run, then every 5 s; stop once it has finished or the request failed. */
function pollEvery(status: RunStatus | undefined, createdAt: string | undefined, failed: boolean) {
  if (failed) return false;
  if (!status) return 1500;
  if (!isActive(status)) return false;
  return createdAt && Date.now() - Date.parse(createdAt) < 30_000 ? 1500 : 5000;
}

export function useQuickRead(campaignId: string, runId: string | null | undefined) {
  return useQuery<QuickReadResult>({
    queryKey: labKeys.result(campaignId, "quick_read", runId),
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/quick-reads/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => pollEvery(q.state.data?.status, q.state.data?.created_at, q.state.status === "error"),
  });
}

export function useAudienceStudy(campaignId: string, runId: string | null | undefined) {
  return useQuery<AudienceStudyResult>({
    queryKey: labKeys.result(campaignId, "audience_study", runId),
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/audience-studies/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => pollEvery(q.state.data?.status, q.state.data?.created_at, q.state.status === "error"),
  });
}

export function useRiskCheck(campaignId: string, runId: string | null | undefined) {
  return useQuery<RiskCheckResult>({
    queryKey: labKeys.result(campaignId, "risk_check", runId),
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/risk-checks/{run_id}", { params: { path: { campaign_id: campaignId, run_id: runId! } } })),
    refetchInterval: (q) => pollEvery(q.state.data?.status, q.state.data?.created_at, q.state.status === "error"),
  });
}

/**
 * Starts a run (202). One Idempotency-Key per distinct request body: a retry of the same body after a network error returns
 * the run the server already created, while a deliberate second run (the key is cleared on success) starts a new one.
 */
function useStarter<B>(campaignId: string, kind: RunKind, post: (body: B, key: string) => Promise<{ run_id: string }>) {
  const qc = useQueryClient();
  const pending = useRef<{ sig: string; key: string } | null>(null);
  return useMutation({
    mutationFn: async (body: B) => {
      const sig = JSON.stringify(body);
      if (pending.current?.sig !== sig) pending.current = { sig, key: newKey() };
      return post(body, pending.current.key);
    },
    onSuccess: () => {
      pending.current = null;
      void qc.invalidateQueries({ queryKey: labKeys.runs(campaignId, kind) });
    },
  });
}

const idem = (key: string) => ({ "Idempotency-Key": key });

export function useStartQuickRead(campaignId: string) {
  return useStarter<QuickReadCreate>(campaignId, "quick_read", (body, key) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/quick-reads", { params: { path: { campaign_id: campaignId } }, body, headers: idem(key) })),
  );
}

export function useStartStudy(campaignId: string) {
  return useStarter<AudienceStudyCreate>(campaignId, "audience_study", (body, key) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/audience-studies", { params: { path: { campaign_id: campaignId } }, body, headers: idem(key) })),
  );
}

export function useStartRiskCheck(campaignId: string) {
  return useStarter<RiskCheckCreate>(campaignId, "risk_check", (body, key) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/risk-checks", { params: { path: { campaign_id: campaignId } }, body, headers: idem(key) })),
  );
}

// ---------- Ask the Panel ----------

export function useParticipants(campaignId: string, runId: string | null | undefined) {
  return useQuery({
    queryKey: labKeys.participants(campaignId, runId),
    enabled: Boolean(runId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/panels/{run_id}/participants", { params: { path: { campaign_id: campaignId, run_id: runId! }, query: { limit: 100 } } })),
    staleTime: 60_000,
  });
}

/** Questions asked of a panel, newest first; with `participantId`, only those that participant answered (their history). */
export function useQuestions(campaignId: string, runId: string | null | undefined, participantId?: string | null) {
  return useQuery({
    queryKey: labKeys.questions(campaignId, runId, participantId),
    enabled: Boolean(runId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/panels/{run_id}/questions", {
          params: { path: { campaign_id: campaignId, run_id: runId! }, query: { limit: 50, participant_id: participantId ?? undefined } },
        }),
      ),
  });
}


export function useAskPanel(campaignId: string, runId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<PanelQuestion, Error, AskBody>({
    mutationFn: (body) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/panels/{run_id}/questions", { params: { path: { campaign_id: campaignId, run_id: runId! } }, body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["lab", campaignId, "questions", runId] }),
  });
}

// ---------- Risk Check findings ----------

function patchFinding(qc: QueryClient, campaignId: string, runId: string, next: RiskCheckFinding) {
  qc.setQueryData<RiskCheckResult>(labKeys.result(campaignId, "risk_check", runId), (old) =>
    old ? { ...old, findings: old.findings.map((f) => (f.id === next.id ? next : f)) } : old,
  );
  // Counts (by status, blocking Go) come from the server, so refetch rather than recompute them here.
  void qc.invalidateQueries({ queryKey: labKeys.result(campaignId, "risk_check", runId) });
  void qc.invalidateQueries({ queryKey: labKeys.runs(campaignId, "risk_check") });
}

export function useUpdateFinding(campaignId: string, runId: string) {
  const qc = useQueryClient();
  return useMutation<RiskCheckFinding, Error, { id: string; status: FindingStatus; reason?: string }>({
    mutationFn: ({ id, status, reason }) =>
      unwrap(
        api.PATCH("/api/v1/campaigns/{campaign_id}/risk-checks/{run_id}/findings/{finding_id}", {
          params: { path: { campaign_id: campaignId, run_id: runId, finding_id: id } },
          body: { status, reason: reason?.trim() || null },
        }),
      ),
    onSuccess: (finding) => patchFinding(qc, campaignId, runId, finding),
  });
}

// ---------- Studio versions and X-Ray scenes (Risk Check input) ----------

export function useStudioVersions(campaignId: string) {
  return useQuery({
    queryKey: ["lab", campaignId, "studio-versions"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions", { params: { path: { campaign_id: campaignId }, query: { limit: 100 } } })),
    select: (page) => page.items,
  });
}

export function useStudioVersion(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: ["lab", campaignId, "studio-version", versionId],
    enabled: Boolean(versionId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}", { params: { path: { campaign_id: campaignId, version_id: versionId! } } })),
  });
}

export function useXRayCreatives(campaignId: string) {
  return useQuery({
    queryKey: ["lab", campaignId, "xray-creatives"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/creatives", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } })),
    select: (page) => page.items.filter((c) => c.status === "completed" || c.status === "partial"),
  });
}

export function useXRayScenes(creativeId: string | null) {
  return useQuery({
    queryKey: ["lab", "xray-scenes", creativeId],
    enabled: Boolean(creativeId),
    queryFn: () => unwrap(api.GET("/api/v1/creatives/{creative_id}/scenes", { params: { path: { creative_id: creativeId! }, query: { limit: 100 } } })),
    select: (page) => page.items,
  });
}
