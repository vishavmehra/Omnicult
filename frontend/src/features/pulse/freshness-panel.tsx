"use client";

import { LoaderCircle, RefreshCw } from "lucide-react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

import { useFreshness, useLoadSample } from "./api";
import { formatDay, formatSpan, platformList } from "./logic";

type Status = components["schemas"]["DatasetStatus"];

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5 px-3 py-2">
      <dt className="type-meta">{label}</dt>
      <dd className="text-[13px] text-ink-body">{children}</dd>
    </div>
  );
}

/** What "fresh" means for what is on screen: the data states, which one applies here, and the sample's own limits. */
export function FreshnessPanel({ campaignId, status }: { campaignId: string; status: Status | undefined }) {
  const loaded = Boolean(status?.loaded);
  const freshness = useFreshness(campaignId, loaded);
  const reload = useLoadSample(campaignId);
  const f = freshness.data;
  const provisionalDays = f?.provisional_days ?? 0;
  const states = [
    { label: "Live", meaning: "Pulled from a connected account within its normal reporting delay.", here: "Not applicable: no account is connected." },
    { label: "Delayed", meaning: "The platform has not reported recently; the last good value is shown with its time.", here: "Not applicable: nothing is pulled." },
    {
      label: "Provisional",
      meaning: "Reported, but the platform may still restate it, for example when conversions arrive late.",
      here: f?.provisional_from ? `The last ${provisionalDays} days, from ${formatDay(f.provisional_from)}. Shaded and dashed in charts, dotted underline in tables.` : "Shown when days are still being reported.",
    },
  ];
  return (
    <div className="space-y-5">
      {f && status?.date_from && status.date_to && (
        <dl className="ledger-rules rounded-card border border-border">
          <Row label="Period">{formatSpan(f.date_from, f.date_to)}</Row>
          <Row label="Refresh">{f.refresh}</Row>
          <Row label="Platforms">{platformList(f.platforms)}</Row>
        </dl>
      )}
      {freshness.error && <ErrorState error={freshness.error} onRetry={() => void freshness.refetch()} />}
      <section aria-label="Data states" className="space-y-2">
        <h3 className="text-[13px] font-semibold text-ink">Data states</h3>
        <dl className="ledger-rules rounded-card border border-border">
          {states.map((s) => (
            <div key={s.label} className="space-y-0.5 px-3 py-2.5">
              <dt className="text-[13px] font-semibold text-ink">{s.label}</dt>
              <dd className="text-[12.5px] text-ink-secondary">{s.meaning}</dd>
              <dd className="text-[12.5px] text-ink-body">
                <span className="font-medium">In this build: </span>
                {s.here}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      {f && <LimitationList items={f.limitations} title="Limits of the sample" />}
      {loaded && (
        <section aria-label="Reload the sample" className="space-y-2">
          <Button variant="outline" size="sm" onClick={() => reload.mutate()} disabled={reload.isPending}>
            {reload.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <RefreshCw aria-hidden />}
            Reload the sample
          </Button>
          <p className="text-[12px] text-ink-muted">Replaces this campaign&apos;s sample rows with an identical copy. Owners and editors only.</p>
          {reload.error && <ErrorState error={reload.error} onRetry={() => reload.mutate()} />}
        </section>
      )}
    </div>
  );
}
