"use client";

import { useQueries } from "@tanstack/react-query";

import { useProjectList } from "@/components/app-shell/project-switcher";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, ProjectSummary, Run } from "@/lib/api/types";

/** Brands (API projects) read for the directory. Bounded so the Today view never fans out without limit. */
export const DIRECTORY_BRAND_LIMIT = 12;

export type DirectoryCampaign = Campaign & { brand: ProjectSummary };

/**
 * Every campaign the account can open, across brands, newest activity first. Used by the header campaign selector and the
 * Today view. One campaigns request per brand (the API has no cross-brand campaign list).
 */
export function useCampaignDirectory({ withRuns = false }: { withRuns?: boolean } = {}) {
  const projects = useProjectList();
  const brands = [...(projects.data?.items ?? [])]
    .sort((a, b) => Date.parse(b.last_activity_at ?? b.updated_at) - Date.parse(a.last_activity_at ?? a.updated_at))
    .slice(0, DIRECTORY_BRAND_LIMIT);

  const campaignQueries = useQueries({
    queries: brands.map((brand) => ({
      queryKey: ["directory", "campaigns", brand.id],
      queryFn: async () =>
        (await unwrap(api.GET("/api/v1/projects/{project_id}/campaigns", { params: { path: { project_id: brand.id }, query: { limit: 100 } } })))
          .items,
    })),
  });

  const runQueries = useQueries({
    queries: brands.map((brand) => ({
      queryKey: ["directory", "runs", brand.id],
      enabled: withRuns,
      queryFn: async () =>
        (await unwrap(api.GET("/api/v1/projects/{project_id}/runs", { params: { path: { project_id: brand.id }, query: { limit: 12 } } }))).items,
      // Keep polling only while something is still moving.
      refetchInterval: (q: { state: { data?: Run[] } }) =>
        q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 5000 : false,
    })),
  });

  const campaigns: DirectoryCampaign[] = brands
    .flatMap((brand, i) => (campaignQueries[i]?.data ?? []).map((c) => ({ ...c, brand })))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));

  const runs = brands
    .flatMap((brand, i) => (runQueries[i]?.data ?? []).map((run) => ({ run, brand })))
    .sort((a, b) => Date.parse(b.run.created_at) - Date.parse(a.run.created_at));

  const error = projects.error ?? campaignQueries.find((q) => q.error)?.error ?? (withRuns ? runQueries.find((q) => q.error)?.error : null) ?? null;
  const pending = projects.isPending || campaignQueries.some((q) => q.isPending);

  return {
    projects,
    brands,
    totalBrands: projects.data?.total ?? 0,
    campaigns,
    runs,
    runsPending: withRuns && runQueries.some((q) => q.isPending),
    pending,
    error,
    refetch: () => {
      void projects.refetch();
      campaignQueries.forEach((q) => void q.refetch());
      if (withRuns) runQueries.forEach((q) => void q.refetch());
    },
  };
}
