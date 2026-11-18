"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import type { components } from "@/lib/api/schema";

import { useMetricCatalogue, useTimeSeries, type Filters } from "./api";
import { formatSpan, platformLabel, platformList, REACH_CAVEAT, regionLabel, shortVersion, slotFor, type GroupBy } from "./logic";
import { TrendChart, type ChartSeries } from "./trend-chart";
import { ReachCaveat, Section, Segmented, SelectField } from "./ui";

type Series = components["schemas"]["Series"];

/** The metrics worth a daily line. Two-week comparisons are single values, so they are not offered here. */
const TREND_METRICS = ["ctr", "cpm", "cpc", "cpa", "roas", "view_rate", "completion_100", "frequency", "reach", "spend", "impressions", "clicks", "conversions"];
const SPLITS: { value: GroupBy; label: string }[] = [
  { value: "version", label: "Version" },
  { value: "region", label: "Region" },
  { value: "platform", label: "Platform" },
  { value: "none", label: "None" },
];

/** What a series is, in words: its split value, named the way the rest of the screen names it. */
function describe(s: Series, groupBy: GroupBy, names: Record<string, string>): { key: string; label: string; slot: number } {
  if (groupBy === "region") return { key: s.region_code ?? "all", label: regionLabel(s.region_code ?? "all", names), slot: slotFor("region", s.region_code ?? "") };
  if (groupBy === "version") return { key: s.version_label ?? "all", label: shortVersion(s.version_label ?? "All versions"), slot: slotFor("version", s.version_label ?? "") };
  if (groupBy === "platform") return { key: s.platform ?? "all", label: platformLabel(s.platform ?? "all"), slot: slotFor("platform", s.platform ?? "") };
  return { key: "all", label: "All versions, regions and platforms in the filters", slot: 1 };
}

export function TrendSection({ campaignId, filters, names }: { campaignId: string; filters: Filters; names: Record<string, string> }) {
  const [metric, setMetric] = useState("ctr");
  const [groupBy, setGroupBy] = useState<GroupBy>("version");
  const catalogue = useMetricCatalogue(campaignId);
  const series = useTimeSeries(campaignId, filters, { metric, groupBy }, true);
  const labelOf = (m: string) => catalogue.data?.items.find((d) => d.name === m)?.label ?? m;
  const definition = catalogue.data?.items.find((d) => d.name === metric);
  const data = series.data;

  const chartSeries: ChartSeries[] = (data?.series ?? []).map((s) => ({
    ...describe(s, groupBy, names),
    points: s.points,
  }));
  const unit = data?.series[0]?.unit ?? definition?.unit ?? "ratio";
  const hasValues = chartSeries.some((s) => s.points.some((p) => p.value !== null));
  const reach = metric === "reach" || metric === "frequency";
  const regionScope = filters.region === "all" ? "All regions" : regionLabel(filters.region, names);
  const platforms = data ? platformList([...new Set(data.series.flatMap((s) => s.platforms))]) : "";

  return (
    <Section
      id="trend"
      title="Daily trend"
      meta={data && <span>{formatSpan(data.date_from, data.date_to)}</span>}
    >
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
        <SelectField
          label="Metric"
          value={metric}
          onChange={setMetric}
          className="w-52"
          options={TREND_METRICS.map((m) => ({ value: m, label: labelOf(m) }))}
        />
        <div className="space-y-1">
          <p className="text-[12px] font-medium text-ink-secondary">Split by</p>
          <Segmented label="Split by" value={groupBy} onChange={setGroupBy} options={SPLITS} />
        </div>
      </div>
      {definition && (
        <p className="max-w-[78ch] text-[12.5px] text-ink-secondary">
          <span className="font-medium text-ink">{definition.label}: </span>
          {definition.description}
          {definition.formula ? <span className="font-mono text-[11.5px] text-ink-muted"> ({definition.formula})</span> : null}
        </p>
      )}
      <div className="rounded-card border border-border bg-surface px-3 py-3.5 sm:px-4">
        {series.error && !data ? (
          <ErrorState error={series.error} onRetry={() => void series.refetch()} />
        ) : !data ? (
          <LoadingState label="Reading the daily series…" />
        ) : !hasValues ? (
          <p className="px-1 py-6 text-[13.5px] text-ink-secondary">
            No values to draw for this slice. A ratio with no denominator is not available, so it is left out rather than drawn as zero.
          </p>
        ) : (
          <TrendChart
            series={chartSeries}
            unit={unit}
            stale={series.isPlaceholderData}
            description={`${labelOf(metric)} per day, ${regionScope}, split by ${groupBy === "none" ? "nothing" : groupBy}, ${formatSpan(data.date_from, data.date_to)}. ${data.label}.`}
          />
        )}
        {data && hasValues && (
          <dl className="type-meta mt-3 grid gap-x-6 gap-y-1 border-t border-border pt-3 sm:grid-cols-3">
            <div>
              <dt className="inline">Platforms: </dt>
              <dd className="inline text-ink-body">{platforms || "none"}</dd>
            </div>
            <div>
              <dt className="inline">Region: </dt>
              <dd className="inline text-ink-body">{regionScope}</dd>
            </div>
            <div>
              <dt className="inline">Version: </dt>
              <dd className="inline text-ink-body">{groupBy === "version" ? "each version separately" : "all versions combined"}</dd>
            </div>
          </dl>
        )}
      </div>
      {reach && <ReachCaveat text={data?.caveats.find((c) => /reach/i.test(c)) ?? REACH_CAVEAT} />}
    </Section>
  );
}
