"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type UsageRow = S["UsageBreakdownRow"];
export type UsagePoint = S["UsageSeriesPoint"];
export type UsageBudget = S["UsageBudgetStatus"];
export type UsageMode = S["UsageReport"]["mode"];

export const PERIODS = [7, 30, 90] as const;

const fetchReport = (workspaceId: string, days: number, mode: UsageMode) =>
  unwrap(api.GET("/api/v1/workspaces/{workspace_id}/usage/report", { params: { path: { workspace_id: workspaceId }, query: { days, mode } } }));

/** What the client returns for the report (the generated component type keeps `actual_cost_usd: null`, which the client drops). */
export type UsageReport = Awaited<ReturnType<typeof fetchReport>>;

/** The full report for one workspace. Everything on the page, including the budget block, comes from this one request. */
export function useUsageReport(workspaceId: string | null, days: number, mode: UsageMode) {
  return useQuery({
    queryKey: ["usage", "report", workspaceId, days, mode],
    enabled: Boolean(workspaceId),
    queryFn: () => fetchReport(workspaceId!, days, mode),
  });
}
