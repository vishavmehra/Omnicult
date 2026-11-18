"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { DataMode, RunStatus, RunType } from "@/lib/api/types";
import { env } from "@/lib/env";

import type { ExportFormat, ProofReportSummary, ProofExport } from "./types";

/** Query keys, so one mutation can refresh exactly what it changed. */
export const proofKeys = {
  reports: (campaignId: string) => ["proof-reports", campaignId] as const,
  report: (id: string) => ["proof-report", id] as const,
  claim: (workspaceId: string, claimId: string) => ["proof-claim", workspaceId, claimId] as const,
};

export function useProofReports(campaignId: string) {
  return useQuery({
    queryKey: proofKeys.reports(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/proof-reports", { params: { path: { campaign_id: campaignId }, query: { limit: 50 } } })),
  });
}

export function useProofReport(reportId: string | null | undefined) {
  return useQuery({
    queryKey: proofKeys.report(reportId ?? ""),
    enabled: Boolean(reportId),
    // A snapshot never changes, so it is safe to keep it for the whole visit.
    staleTime: Infinity,
    queryFn: () => unwrap(api.GET("/api/v1/proof-reports/{report_id}", { params: { path: { report_id: reportId! } } })),
  });
}

/** Report assembly is deterministic and synchronous: the response is the finished snapshot. */
export function useCreateProofReport(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { title?: string; region_codes?: string[] }) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/proof-reports", { params: { path: { campaign_id: campaignId } }, body })),
    onSuccess: (report) => {
      queryClient.setQueryData(proofKeys.report(report.id), report);
      return queryClient.invalidateQueries({ queryKey: proofKeys.reports(campaignId) });
    },
  });
}

export function useSectionInfo() {
  return useQuery({
    queryKey: ["proof-report-sections"],
    staleTime: 10 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/proof-report-sections")),
  });
}

// --- exports ---------------------------------------------------------------------------------------------------

export const EXPORT_LABEL: Record<ExportFormat, string> = { pdf: "PDF", json: "JSON", markdown: "Markdown" };
const EXPORT_EXT: Record<ExportFormat, string> = { pdf: "pdf", json: "json", markdown: "md" };

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Download a snapshot now, through the signed-in request (the server keeps the disclosures and labels in every format). */
export async function downloadReport(report: Pick<ProofReportSummary, "id" | "title" | "version_number">, format: ExportFormat) {
  let response: Response | undefined;
  const blob = await unwrap(
    api
      .GET("/api/v1/proof-reports/{report_id}/export", { params: { path: { report_id: report.id }, query: { format } }, parseAs: "blob" })
      .then((result) => {
        response = result.response;
        return result;
      }),
  );
  // The server names the file (Content-Disposition); the local name is only a fallback.
  const slug = report.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "proof-report";
  const named = /filename="([^"]+)"/.exec(response?.headers.get("content-disposition") ?? "")?.[1];
  saveBlob(blob as Blob, named ?? `${slug}-v${report.version_number}.${EXPORT_EXT[format]}`);
}

/** A stored export: the API keeps a copy and returns a link that works without sign-in until `expires_at`. */
export function useCreateStoredExport(reportId: string) {
  return useMutation({
    mutationFn: (format: ExportFormat): Promise<ProofExport> =>
      unwrap(api.POST("/api/v1/proof-reports/{report_id}/exports", { params: { path: { report_id: reportId } }, body: { format } })),
  });
}

/** `download_url` is an API path; make it absolute against the configured API host. */
export const absoluteDownloadUrl = (path: string) => (/^https?:\/\//.test(path) ? path : `${env.apiBaseUrl.replace(/\/$/, "")}${path}`);

// --- run history -----------------------------------------------------------------------------------------------

export const RUN_HISTORY_PAGE = 20;

export function useRunHistory(campaignId: string, filter: { runType?: RunType; status?: RunStatus; page: number }) {
  return useQuery({
    queryKey: ["proof-run-history", campaignId, filter],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/run-history", {
          params: {
            path: { campaign_id: campaignId },
            query: { limit: RUN_HISTORY_PAGE, offset: filter.page * RUN_HISTORY_PAGE, run_type: filter.runType, status: filter.status },
          },
        }),
      ),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "queued" || r.status === "running") ? 5000 : false),
  });
}

export function useRunDetail(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["proof-run-detail", runId],
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/runs/{run_id}/history", { params: { path: { run_id: runId } } })),
  });
}

// --- data health, claims, regions ----------------------------------------------------------------------------------

export function useDataHealth(workspaceId: string | null, mode: DataMode) {
  return useQuery({
    queryKey: ["proof-data-health", workspaceId, mode],
    enabled: Boolean(workspaceId),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/data-health", { params: { path: { workspace_id: workspaceId! }, query: { mode } } })),
  });
}

export function useClaim(workspaceId: string | null, claimId: string | null) {
  return useQuery({
    queryKey: proofKeys.claim(workspaceId ?? "", claimId ?? ""),
    enabled: Boolean(workspaceId && claimId),
    staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/claims/{claim_id}", { params: { path: { workspace_id: workspaceId!, claim_id: claimId! } } })),
  });
}

/** Stored conflicts of one region, both sides included; the drawer keeps the ones that involve the open claim. */
export function useRegionConflicts(workspaceId: string | null, regionCode: string | null | undefined, mode: DataMode) {
  return useQuery({
    queryKey: ["proof-conflicts", workspaceId, regionCode, mode],
    enabled: Boolean(workspaceId && regionCode),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conflicts", {
          params: { path: { workspace_id: workspaceId! }, query: { region_code: regionCode!, mode, limit: 100 } },
        }),
      ),
  });
}

export function useRegions() {
  return useQuery({
    queryKey: ["proof-regions", "IN"],
    staleTime: 60 * 60_000,
    queryFn: async () => (await unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: "IN", limit: 100 } } }))).items,
  });
}

// --- evidence map and search -----------------------------------------------------------------------------------

export function useProofGraph(projectId: string, campaignId: string, regionCode: string, limit: number) {
  return useQuery({
    queryKey: ["proof-graph", projectId, campaignId, regionCode, limit],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/evidence-graph", {
          params: { path: { project_id: projectId }, query: { campaign_id: campaignId, region_code: regionCode || undefined, limit } },
        }),
      ),
  });
}

export function useProofSearch(projectId: string, query: string, regionCode: string, kinds: string[]) {
  return useQuery({
    queryKey: ["proof-search", projectId, query, regionCode, kinds],
    enabled: query.length > 0,
    staleTime: 60_000,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/search", {
          params: {
            path: { project_id: projectId },
            query: { q: query, limit: 25, region_code: regionCode || undefined, kinds: kinds.length ? (kinds as never) : undefined },
          },
        }),
      ),
  });
}
