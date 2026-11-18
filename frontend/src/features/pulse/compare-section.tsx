"use client";

import { ArrowDown, ArrowUp, Equal, Minus } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useVersionComparison, type Filters } from "./api";
import {
  formatPctChange, formatPoints, formatSpan, formatValue, isWindowChange, judge, platformLabel, platformList, shortVersion, slotFor, sortRegions, standout, type ComparedMetric, type Judgement,
} from "./logic";
import { SampleTag, Section, Segmented, SelectField, slotColor, NotAvailable } from "./ui";

type Status = components["schemas"]["DatasetStatus"];
type Region = components["schemas"]["RegionComparison"];

/** The metrics the bars can show. The table twin below carries all seven the API compares. */
const BAR_METRICS = [
  { value: "ctr", label: "CTR" },
  { value: "cpa", label: "CPA" },
  { value: "roas", label: "ROAS" },
  { value: "cpm", label: "CPM" },
  { value: "view_rate", label: "View rate" },
  { value: "completion_100", label: "100% completion" },
] as const;

function Delta({ metric, m }: { metric: string; m: ComparedMetric }) {
  const j: Judgement = judge(metric, m.delta_pct_vs_baseline, m.delta_vs_baseline);
  const windowChange = isWindowChange(metric);
  const text = windowChange ? formatPoints(m.delta_vs_baseline) : formatPctChange(m.delta_pct_vs_baseline);
  if (m.delta_vs_baseline === null) return <NotAvailable />;
  const Icon = j === "same" ? Equal : j === "neutral" ? Minus : m.delta_vs_baseline > 0 ? ArrowUp : ArrowDown;
  const word = j === "better" ? "better" : j === "worse" ? "worse" : j === "same" ? "about the same" : "";
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap", j === "better" && "text-success", j === "worse" && "text-danger", (j === "same" || j === "neutral") && "text-ink-secondary")}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      <span className="font-medium tabular-nums">{text}</span>
      {word && <span className="text-[12px]">{word}</span>}
    </span>
  );
}

function RegionBars({ region, metric, scaleMax, label }: { region: Region; metric: string; scaleMax: number; label: string }) {
  return (
    <li className="grid gap-x-4 gap-y-1.5 py-3 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
      <div>
        <p className="text-[13.5px] font-semibold text-ink">{region.region_name}</p>
        <p className="type-meta">Baseline: {shortVersion(region.baseline_version)}</p>
      </div>
      <ul className="space-y-1.5" aria-label={`${label} by version in ${region.region_name}`}>
        {region.versions.map((v) => {
          const m = v.metrics.find((x) => x.metric === metric);
          const pct = m?.value ? Math.min(100, (m.value / scaleMax) * 100) : 0;
          return (
            <li key={v.version_label} className="grid grid-cols-[5.25rem_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 sm:grid-cols-[5.25rem_minmax(0,1fr)_auto]">
              <span className="text-[12.5px] text-ink-secondary" title={v.version_label}>
                {shortVersion(v.version_label)}
              </span>
              <span className="flex min-w-0 items-center gap-2 border-l border-border-strong/60">
                {pct > 0 && (
                  <span
                    aria-hidden
                    className="block h-3.5 shrink-0 rounded-r-[4px]"
                    style={{ width: `${pct * 0.78}%`, backgroundColor: slotColor(slotFor("version", v.version_label)) }}
                  />
                )}
                <span className="text-[13px] font-semibold text-ink tabular-nums">
                  {m ? m.value === null ? <NotAvailable /> : formatValue(m.value, m.unit) : <NotAvailable />}
                  {m?.provisional && <span className="sr-only"> (includes provisional days)</span>}
                </span>
              </span>
              <span className="col-start-2 text-[12.5px] sm:col-start-auto sm:justify-self-end">
                {v.is_baseline ? <span className="text-ink-muted">Baseline</span> : m ? <Delta metric={metric} m={m} /> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </li>
  );
}

export function CompareSection({ campaignId, status, filters, names }: { campaignId: string; status: Status; filters: Filters; names: Record<string, string> }) {
  const [metric, setMetric] = useState<string>("ctr");
  const [baseline, setBaseline] = useState<string>("");
  const cmp = useVersionComparison(campaignId, filters, baseline || null, true);
  const data = cmp.data && { ...cmp.data, regions: sortRegions(cmp.data.regions, (r) => r.region_code) };
  const label = BAR_METRICS.find((m) => m.value === metric)?.label ?? metric;
  const absent = sortRegions(status.regions, (r) => r).filter((r) => !data?.regions.some((x) => x.region_code === r) && (filters.region === "all" || filters.region === r));

  const scaleMax = Math.max(0, ...(data?.regions.flatMap((r) => r.versions.map((v) => v.metrics.find((m) => m.metric === metric)?.value ?? 0)) ?? []));
  const leaders = (data?.regions ?? []).flatMap((r) => {
    const s = standout(r, metric);
    if (!s) return [];
    const unit = r.versions[0].metrics.find((m) => m.metric === metric)?.unit ?? "ratio";
    const base = shortVersion(r.baseline_version);
    return [
      {
        key: r.region_code,
        text: s.baselineLeads
          ? `${r.region_name}: the baseline (${base}) leads on ${label}. No other version beats it here.`
          : `${r.region_name}: ${shortVersion(s.versionLabel)} leads on ${label}, ${formatValue(s.value, unit)} against ${formatValue(s.baselineValue, unit)} for ${base} (${formatPctChange(s.deltaPct)}).`,
      },
    ];
  });

  return (
    <Section
      id="compare"
      title="Versions compared"
      meta={
        <>
          <SampleTag />
          {data && <span>{formatSpan(data.date_from, data.date_to)}</span>}
        </>
      }
    >
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
        <div className="space-y-1">
          <p className="text-[12px] font-medium text-ink-secondary">Metric</p>
          <Segmented label="Metric" value={metric} onChange={setMetric} options={BAR_METRICS.map((m) => ({ value: m.value, label: m.label }))} />
        </div>
        <SelectField
          label="Baseline version"
          value={baseline}
          onChange={setBaseline}
          className="w-64"
          options={[{ value: "", label: "Default: the version that started first" }, ...status.versions.map((v) => ({ value: v, label: v }))]}
        />
      </div>

      {cmp.error && !data ? (
        <ErrorState error={cmp.error} onRetry={() => void cmp.refetch()} />
      ) : !data ? (
        <LoadingState label="Comparing versions…" />
      ) : data.regions.length === 0 ? (
        <EmptyState
          title="Nothing to compare in this slice"
          description="A comparison needs at least two versions that ran in the same region. In the current filters only one did, or the chosen baseline did not run there."
        />
      ) : (
        <div className={cn("space-y-4 transition-opacity", cmp.isPlaceholderData && "opacity-60")} aria-busy={cmp.isPlaceholderData}>
          <ul aria-label="What stands out" className="max-w-[78ch] space-y-1 text-[13.5px] text-ink-body">
            {leaders.map((l) => (
              <li key={l.key}>{l.text}</li>
            ))}
          </ul>
          <div className="rounded-card border border-border bg-surface px-4 py-1.5">
            <ul className="ledger-rules">
              {data.regions.map((r) => (
                <RegionBars key={r.region_code} region={r} metric={metric} scaleMax={scaleMax} label={label} />
              ))}
            </ul>
            <p className="type-meta border-t border-border py-2.5">
              Bars share one scale across regions and start at zero. Platforms: {data.platform ? platformLabel(data.platform) : platformList(status.platforms)} · last updated {formatDateTime(data.last_updated_at)}
              . Values include provisional days unless the period is set to Settled days only.
            </p>
          </div>
          <ul aria-label="Version colours" className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-secondary">
            {status.versions.map((v) => (
              <li key={v} className="flex items-center gap-1.5">
                <span aria-hidden className="size-2.5 rounded-[3px]" style={{ backgroundColor: slotColor(slotFor("version", v)) }} />
                {v}
              </li>
            ))}
          </ul>
          {absent.length > 0 && (
            <p className="max-w-[78ch] text-[12.5px] text-ink-secondary">
              <span className="font-medium text-ink">Not compared: </span>
              {absent.map((r) => names[r] ?? r).join(", ")}. Only one version ran there (or the chosen baseline did not), so there is nothing to set it against.
            </p>
          )}
          <p className="max-w-[78ch] text-[12.5px] leading-snug text-ink-secondary">
            <span className="font-medium text-ink">How to read this. </span>
            Each adapted version is measured against the baseline in the same region. Where an adapted version is better, the baseline is underperforming there. The
            differences are descriptive: this is not an experiment, there is no significance test, and nothing here says how a real campaign would perform.
          </p>
          <details className="text-[12.5px]">
            <summary className="inline-flex cursor-pointer items-center text-ink-secondary hover:text-ink">All compared metrics as a table</summary>
            <div className="mt-2 overflow-x-auto rounded-lg border border-border">
              <table className="type-ledger w-full min-w-[40rem] text-left text-[12.5px]">
                <caption className="sr-only">Every compared metric by region and version, with the change against the baseline version.</caption>
                <thead className="bg-surface-muted text-ink-secondary">
                  <tr>
                    <th scope="col" className="px-3 py-1.5 font-medium">Region and version</th>
                    {data.regions[0].versions[0].metrics.map((m) => (
                      <th key={m.metric} scope="col" className="px-3 py-1.5 text-right font-medium">{m.label}</th>
                    ))}
                  </tr>
                </thead>
                {data.regions.map((r) => (
                  <tbody key={r.region_code} className="divide-y divide-border border-t border-border">
                    {r.versions.map((v) => (
                      <tr key={v.version_label}>
                        <th scope="row" className="px-3 py-1.5 font-normal text-ink">
                          <span className="block">{names[r.region_code] ?? r.region_name}</span>
                          <span className="block text-[11.5px] text-ink-muted">{v.version_label}{v.is_baseline ? " (baseline)" : ""}</span>
                        </th>
                        {v.metrics.map((m) => (
                          <td key={m.metric} className="px-3 py-1.5 text-right align-top tabular-nums">
                            <span className={cn("block text-ink", m.provisional && "underline decoration-ink-muted decoration-dotted underline-offset-4")}>
                              {m.value === null ? <NotAvailable /> : formatValue(m.value, m.unit, { signed: isWindowChange(m.metric) })}
                            </span>
                            {!v.is_baseline && (
                              <span className="block text-[11.5px]">
                                <Delta metric={m.metric} m={m} />
                              </span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                ))}
              </table>
            </div>
          </details>
        </div>
      )}
    </Section>
  );
}
