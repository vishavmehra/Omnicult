"use client";

import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { formatSpan, formatValue, platformList, REACH_CAVEAT, sortRegions } from "./logic";
import { NotAvailable, ReachCaveat, Section } from "./ui";

type Summary = components["schemas"]["RegionSummary"];
type Value = components["schemas"]["MetricValue"];

const GROUP_LABEL: Record<string, string> = {
  delivery: "Delivery",
  cost: "Cost",
  response: "Response",
  video: "Video",
  outcome: "Outcome",
  creative_health: "Creative health",
};

/** Raw quartile counts are hidden until asked for: the completion rates beside them say the same thing per impression. */
const RAW_COUNTS = new Set(["video_q25", "video_q50", "video_q75", "video_q100"]);
const ROW_NOTE: Record<string, string> = {
  reach: "cumulative, not deduplicated",
  frequency: "from cumulative reach",
  ctr_change_vs_first_week: "last 7 settled days against the first 7",
  view_rate_change_vs_first_week: "last 7 settled days against the first 7",
};

function cellTitle(v: Value, regionName: string) {
  return [
    `${regionName}: ${v.label}`,
    `Platforms: ${platformList(v.platforms)}`,
    `Range: ${formatSpan(v.date_from, v.date_to)}`,
    `Last updated: ${formatDateTime(v.last_updated_at)}`,
    v.provisional ? "Includes provisional days" : "Settled days only",
  ].join("\n");
}

/**
 * The four regions side by side: one column per region, metrics down the rows grouped as the API groups them. A value shows
 * its platforms on the row and a dotted underline when it includes provisional days.
 */
export function RegionLedger({ data, stale }: { data: Summary; stale: boolean }) {
  const [raw, setRaw] = useState(false);
  const regions = sortRegions(data.regions, (r) => r.region_code);
  const reachShown = regions.some((r) => r.groups.some((g) => g.metrics.some((m) => m.metric === "reach" || m.metric === "frequency")));
  const anyProvisional = regions.some((r) => r.groups.some((g) => g.metrics.some((m) => m.provisional)));
  const first = regions[0];
  const groupIds = first ? first.groups.map((g) => g.group) : [];

  return (
    <Section
      id="regions"
      title="Regions side by side"
      meta={<span>{formatSpan(data.date_from, data.date_to)}</span>}
    >
      <p className="type-meta flex flex-wrap gap-x-3 gap-y-0.5">
        <span>Platforms: {data.platform ? platformList([data.platform]) : platformList(first?.groups[0]?.metrics[0]?.platforms ?? [])}</span>
        {anyProvisional && <span>Dotted underline: includes provisional days</span>}
      </p>
      <div className={cn("relative overflow-x-auto rounded-card border border-border bg-surface transition-opacity", stale && "opacity-60")} aria-busy={stale}>
        <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
          <caption className="sr-only">
            Metrics by region for {formatSpan(data.date_from, data.date_to)}. {data.label}.
          </caption>
          <thead className="bg-surface-muted text-[12px] text-ink-secondary">
            <tr>
              <th scope="col" className="sticky left-0 bg-surface-muted px-3 py-2.5 font-medium">
                Metric
              </th>
              {regions.map((r) => (
                <th key={r.region_code} scope="col" className="px-3 py-2.5 text-right font-medium">
                  <span className="block text-[13px] font-semibold text-ink">{r.region_name}</span>
                  <span className="block font-mono text-[11px] font-normal text-ink-muted">{r.region_code}</span>
                  <span className="block text-[11.5px] font-normal text-ink-muted">
                    {r.versions.length} {r.versions.length === 1 ? "version" : "versions"}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          {groupIds.map((g) => {
            const rows = first!.groups.find((x) => x.group === g)!.metrics.filter((m) => raw || !RAW_COUNTS.has(m.metric));
            if (!rows.length) return null;
            return (
              <tbody key={g} className="divide-y divide-border border-t border-border">
                <tr>
                  <th scope="rowgroup" colSpan={regions.length + 1} className="sticky left-0 bg-surface-muted/60 px-3 py-1.5 text-[12px] font-semibold text-ink-secondary">
                    {GROUP_LABEL[g] ?? g}
                  </th>
                </tr>
                {rows.map((m) => (
                  <tr key={m.metric}>
                    <th scope="row" className="sticky left-0 bg-surface px-3 py-2 font-normal">
                      <span className="block text-ink">{m.label}</span>
                      <span className="block text-[11.5px] text-ink-muted">
                        {ROW_NOTE[m.metric] ? `${ROW_NOTE[m.metric]} · ` : ""}
                        {platformList(m.platforms)}
                      </span>
                    </th>
                    {regions.map((r) => {
                      const v = r.groups.find((x) => x.group === g)?.metrics.find((x) => x.metric === m.metric);
                      return (
                        <td key={r.region_code} className="px-3 py-2 text-right align-top">
                          {v ? (
                            <span title={cellTitle(v, r.region_name)} className={cn("text-ink tabular-nums", v.provisional && "underline decoration-ink-muted decoration-dotted underline-offset-4")}>
                              {v.value === null ? <NotAvailable /> : formatValue(v.value, v.unit, { compact: !raw, signed: v.metric.endsWith("_change_vs_first_week") })}
                              {v.provisional && <span className="sr-only"> (includes provisional days)</span>}
                            </span>
                          ) : (
                            <NotAvailable />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
      <div className="space-y-2">
        <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-secondary">
          <input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} className="size-4 accent-[var(--pop)]" />
          Show raw quartile counts and exact figures
        </label>
        {reachShown && <ReachCaveat text={data.caveats.find((c) => /reach/i.test(c)) ?? REACH_CAVEAT} />}
      </div>
    </Section>
  );
}
