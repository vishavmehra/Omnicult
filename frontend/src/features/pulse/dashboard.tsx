"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

import { AlertsSection } from "./alerts-section";
import { DEFAULT_FILTERS, useSummary, type Filters } from "./api";
import { CompareSection } from "./compare-section";
import { FilterRow } from "./filters";
import { REGION_FALLBACK } from "./logic";
import { RegionLedger } from "./region-ledger";
import { TrendSection } from "./trend-section";
import { PULSE_THEME } from "./ui";

type Status = components["schemas"]["DatasetStatus"];

/** The loaded dashboard: one filter row, then the sections it scopes, then the alert preview with its own thresholds. */
export function Dashboard({ campaignId, status }: { campaignId: string; status: Status }) {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const summary = useSummary(campaignId, filters, true);
  const names: Record<string, string> = { ...REGION_FALLBACK };
  for (const r of summary.data?.regions ?? []) names[r.region_code] = r.region_name;

  return (
    <div className={cn("space-y-8", PULSE_THEME)}>
      <FilterRow status={status} value={filters} onChange={setFilters} names={names} />
      {summary.error && !summary.data ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : !summary.data ? (
        <LoadingState label="Reading the regional summary…" />
      ) : (
        <RegionLedger data={summary.data} stale={summary.isPlaceholderData} provisionalFrom={status.provisional_from} />
      )}
      <TrendSection campaignId={campaignId} filters={filters} names={names} />
      <CompareSection campaignId={campaignId} status={status} filters={filters} names={names} />
      <AlertsSection campaignId={campaignId} names={names} />
    </div>
  );
}
