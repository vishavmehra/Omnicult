"use client";

import { CountUp, Reveal, Sparkline, TiltCard } from "@/components/creative";
import { cn } from "@/lib/utils";

import { ALL_REGIONS, useSummary, useTimeSeries, type Filters } from "./api";
import { formatDay, formatValue, regionLabel, sortRegions } from "./logic";
import { NotAvailable, ProvisionalTag, Section } from "./ui";

/** The one metric the cards lead with. It comes from the API's summary; the daily line behind it is the same metric. */
const KEY_METRIC = "ctr";

/**
 * One tilt card per region: the key metric counting up, its daily line (hover or arrow keys to read a day), and a click
 * that scopes the ledger and the trend below to that region (click again to go back to all). The cards always read all
 * regions, so choosing one does not make the others disappear.
 */
export function RegionCards({ campaignId, filters, names, onRegion }: { campaignId: string; filters: Filters; names: Record<string, string>; onRegion: (region: string) => void }) {
  const all: Filters = { ...filters, region: ALL_REGIONS };
  const summary = useSummary(campaignId, all, true);
  const series = useTimeSeries(campaignId, all, { metric: KEY_METRIC, groupBy: "region" }, true);
  const regions = sortRegions(summary.data?.regions ?? [], (r) => r.region_code);
  if (regions.length === 0) return null;

  return (
    <Section id="region-cards" title="Regions at a glance" meta={<span>Select a region to scope the sections below</span>}>
      <ul aria-label="Regions" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {regions.map((r, i) => {
          const metric = r.groups.flatMap((g) => g.metrics).find((m) => m.metric === KEY_METRIC);
          const points = (series.data?.series.find((s) => s.region_code === r.region_code)?.points ?? []).filter((p): p is typeof p & { value: number } => p.value !== null);
          const on = filters.region === r.region_code;
          const name = regionLabel(r.region_code, names);
          return (
            <Reveal as="li" key={r.region_code} index={i}>
              <TiltCard className={cn("bento h-full space-y-2 p-4!", on && "ring-2 ring-pop ring-offset-2 ring-offset-surface")}>
                <button
                  type="button"
                  aria-pressed={on}
                  aria-label={`${name}${metric ? `, ${metric.label} ${formatValue(metric.value, metric.unit)}` : ""}. ${on ? "Showing only this region. Press to show all regions." : "Press to show only this region below."}`}
                  onClick={() => onRegion(on ? ALL_REGIONS : r.region_code)}
                  className="block w-full text-left outline-none after:absolute after:inset-0 after:rounded-[inherit] focus-visible:after:ring-2 focus-visible:after:ring-pop"
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="text-[15px] font-semibold text-ink">{name}</span>
                    <span className="font-mono text-[11px] text-ink-muted">{r.region_code}</span>
                  </span>
                  <span className="mt-2 block text-[12px] text-ink-secondary">{metric?.label ?? "Click-through rate"}</span>
                  <span className="block text-[30px] leading-tight font-semibold text-ink tabular-nums">
                    {metric && metric.value !== null ? <CountUp value={metric.value} format={(n) => formatValue(n, metric.unit)} /> : <NotAvailable />}
                  </span>
                  <span className="type-meta">
                    {r.versions.length} {r.versions.length === 1 ? "version" : "versions"}
                  </span>
                </button>
                {metric?.provisional && <ProvisionalTag className="relative z-10" />}
                {points.length > 1 && (
                  <div className="relative z-10 -mx-1">
                    <Sparkline
                      variant="area"
                      tone="pulse"
                      height={48}
                      values={points.map((p) => p.value)}
                      labels={points.map((p) => formatDay(p.date) + (p.provisional ? " (provisional)" : ""))}
                      format={(v) => formatValue(v, metric?.unit ?? "ratio")}
                      ariaLabel={`${name}, ${metric?.label ?? KEY_METRIC} per day`}
                    />
                  </div>
                )}
              </TiltCard>
            </Reveal>
          );
        })}
      </ul>
    </Section>
  );
}
