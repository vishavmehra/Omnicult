"use client";

import { CircleCheck, CircleDashed, Eye, Flame, RotateCcw, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Verdict } from "@/components/workflow/verdict";
import { formatValue, shortVersion } from "@/features/pulse/logic";
import { ReachCaveat, Section } from "@/features/pulse/ui";
import { cn } from "@/lib/utils";

import { useFatigue } from "./api";
import { FatigueChart } from "./fatigue-chart";
import {
  FATIGUE_DEFAULTS, FATIGUE_STATUS, parseFatigueForm, PATTERN_LABEL, type FatigueForm, type FatigueRow, type FatigueSignal,
} from "./logic";
import { NumberField, PulseTabPage } from "./ui";

const STATUS_STYLE: Record<FatigueRow["status"], { tone: string; Icon: LucideIcon }> = {
  fatigued: { tone: "border-danger/30 bg-danger-soft text-danger", Icon: Flame },
  watch: { tone: "border-warning/30 bg-warning-soft text-warning", Icon: Eye },
  healthy: { tone: "border-success/25 bg-success-soft text-success", Icon: CircleCheck },
  not_enough_data: { tone: "border-border bg-surface-muted text-ink-secondary", Icon: CircleDashed },
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function observedText(s: FatigueSignal): string {
  if (s.observed === null) return "n/a";
  if (s.name === "frequency") return formatValue(s.observed, "multiple");
  if (s.name === "repeated_exposure") return `${Math.round(s.observed * 100)}% of the first week`;
  return `${s.observed > 0 ? "+" : ""}${(s.observed * 100).toFixed(1)}% vs first week`;
}

function thresholdText(s: FatigueSignal): string {
  if (s.threshold === null) return "";
  if (s.name === "frequency") return `at or above ${formatValue(s.threshold, "multiple")}`;
  if (s.name === "repeated_exposure") return `at or below ${Math.round(s.threshold * 100)}%`;
  return `at or below -${(Math.abs(s.threshold) * 100).toFixed(0)}%`;
}

function Signals({ row }: { row: FatigueRow }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="type-ledger w-full min-w-[30rem] text-left text-[12.5px]">
        <caption className="sr-only">The four fatigue signals for this version in this region: what was observed, the threshold, and whether it fired.</caption>
        <thead className="bg-surface-muted text-ink-secondary">
          <tr>
            <th scope="col" className="px-3 py-1.5 font-medium">Signal</th>
            <th scope="col" className="px-3 py-1.5 font-medium">Observed</th>
            <th scope="col" className="px-3 py-1.5 font-medium">Flags when</th>
            <th scope="col" className="px-3 py-1.5 font-medium">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {row.signals.map((s) => (
            <tr key={s.name} className="align-top" title={s.detail}>
              <th scope="row" className="px-3 py-1.5 font-normal text-ink">
                {s.label}
                <span className="block text-[11px] text-ink-muted">{s.family === "response" ? "Response" : "Exposure"}</span>
              </th>
              <td className="px-3 py-1.5 tabular-nums text-ink">{s.available ? observedText(s) : <span className="text-ink-muted">Not available</span>}</td>
              <td className="px-3 py-1.5 text-ink-secondary">{thresholdText(s)}</td>
              <td className={cn("px-3 py-1.5 font-medium", s.triggered ? "text-danger" : "text-ink-secondary")}>{!s.available ? "Cannot read" : s.triggered ? "Fired" : "Clear"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RowCard({ row, campaignId, threshold }: { row: FatigueRow; campaignId: string; threshold: number }) {
  const { tone, Icon } = STATUS_STYLE[row.status];
  const assessed = row.status !== "not_enough_data";
  return (
    <li className="space-y-3 px-4 py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="text-[14px] font-semibold text-ink" title={row.version_label}>
          {shortVersion(row.version_label)}
        </p>
        <Tag className={tone}>
          <Icon aria-hidden />
          {FATIGUE_STATUS[row.status].label}
        </Tag>
        {assessed && <span className="text-[12.5px] text-ink-secondary">{PATTERN_LABEL[row.pattern]}</span>}
        <span className="sm:ml-auto">
          <ConfidenceIndicator level={row.confidence === "High" ? "high" : row.confidence === "Moderate" ? "moderate" : "low"} />
        </span>
      </div>
      <p className="max-w-[78ch] text-[13px] leading-snug text-ink-body">{row.reason}</p>
      {assessed && (
        row.status === "healthy" ? (
          <details className="text-[12.5px]">
            <summary className="cursor-pointer text-ink-secondary hover:text-ink">Show the evidence</summary>
            <div className="mt-3 space-y-3">
          <div className="grid gap-x-6 gap-y-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <FatigueChart title="CTR by day" unit="ratio" points={row.ctr} from={row.window_from} to={row.window_to} slot={1} />
            <FatigueChart title="Frequency by day" unit="multiple" points={row.frequency} from={row.window_from} to={row.window_to} slot={2} threshold={threshold} thresholdLabel={`threshold ${threshold}×`} />
          </div>
          <Signals row={row} />
          {row.signals.some((s) => s.name === "frequency" && s.available) && <ReachCaveat className="text-[12px]" />}
            </div>
          </details>
        ) : (
          <>
          <div className="grid gap-x-6 gap-y-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <FatigueChart title="CTR by day" unit="ratio" points={row.ctr} from={row.window_from} to={row.window_to} slot={1} />
            <FatigueChart title="Frequency by day" unit="multiple" points={row.frequency} from={row.window_from} to={row.window_to} slot={2} threshold={threshold} thresholdLabel={`threshold ${threshold}×`} />
          </div>
          <Signals row={row} />
          {row.signals.some((s) => s.name === "frequency" && s.available) && <ReachCaveat className="text-[12px]" />}
          </>
        )
      )}
      {row.refresh.length > 0 && (
        <div className="space-y-1.5 rounded-lg border border-border bg-surface-muted px-3.5 py-2.5">
          <p className="text-[12.5px] font-semibold text-ink">Suggested refresh</p>
          <ul className="space-y-1.5">
            {row.refresh.map((r) => (
              <li key={`${r.kind}|${r.label}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 text-[13px] text-ink-body">
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-ink">{r.label}.</span> {r.detail}
                </span>
                {r.verdict && <Verdict value={r.verdict} />}
                {r.kind !== "pulse_version" && (
                  <Link href={`/app/c/${campaignId}/studio`} className="text-[12.5px] font-medium text-ink underline underline-offset-4 hover:text-ink-secondary">
                    Open Creative Studio
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

/** Fatigue Watch (feature 47): per version and region, the evidence for or against wear-out, a computed reason and a suggested refresh. */
export function FatigueTab({ campaignId }: { campaignId: string }) {
  const [form, setForm] = useState<FatigueForm>(FATIGUE_DEFAULTS);
  const parsed = parseFatigueForm(form);
  const settled = parseFatigueForm(useDebounced(form, 350));
  const report = useFatigue(campaignId, settled.ok ? settled.query : null); // an invalid field keeps the last reading on screen
  const errors = parsed.ok ? {} : parsed.errors;
  const set = (k: keyof FatigueForm) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const dirty = JSON.stringify(form) !== JSON.stringify(FATIGUE_DEFAULTS);
  const data = report.data;
  const totals = data ? data.regions.reduce((a, r) => ({ fatigued: a.fatigued + r.fatigued, watch: a.watch + r.watch }), { fatigued: 0, watch: 0 }) : null;

  return (
    <PulseTabPage>
      <Section id="fatigue" title="Fatigue Watch">
        <details className="rounded-card border border-border bg-surface" open={false}>
          <summary className="cursor-pointer px-4 py-2.5 text-[13px] text-ink-secondary hover:text-ink">How a version is read, and the thresholds</summary>
          <div className="space-y-4 border-t border-border px-4 py-3">
            {data && (
              <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-ink-body marker:text-ink-muted">
                {data.method.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            )}
            <fieldset className="space-y-3">
              <legend className="sr-only">Fatigue thresholds</legend>
              <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
                <NumberField label="CTR has fallen at least" suffix="% below the first week" step="1" value={form.ctr} onChange={set("ctr")} error={errors.ctr} />
                <NumberField label="View rate has fallen at least" suffix="% below the first week" step="1" value={form.viewRate} onChange={set("viewRate")} error={errors.viewRate} />
                <NumberField label="Frequency is at or above" suffix="×" step="0.1" value={form.frequency} onChange={set("frequency")} error={errors.frequency} />
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="outline" size="sm" disabled={!dirty} onClick={() => setForm(FATIGUE_DEFAULTS)}>
                  <RotateCcw aria-hidden />
                  Reset to defaults
                </Button>
                <p className="type-meta">Reading updates as you type. Out-of-range values are not sent.</p>
              </div>
            </fieldset>
          </div>
        </details>

        {report.error && !data ? (
          <ErrorState error={report.error} onRetry={() => void report.refetch()} />
        ) : !data ? (
          <LoadingState label="Reading CTR, view rate, frequency and reach…" />
        ) : data.regions.length === 0 ? (
          <EmptyState title="Nothing to read" description="The Pulse series has no version and region to assess." />
        ) : (
          <div className={cn("space-y-5 transition-opacity", report.isPlaceholderData && "opacity-60")} aria-busy={report.isPlaceholderData}>
            <p className="type-ledger text-[13px] text-ink-body" aria-live="polite">
              <span className="font-semibold text-ink">{totals?.fatigued ?? 0} fatigued</span>, {totals?.watch ?? 0} on watch, across {data.regions.reduce((n, r) => n + r.rows.length, 0)} versions in {data.regions.length} regions.
            </p>
            {data.regions.map((region) => (
              <section key={region.region_code} aria-labelledby={`fatigue-${region.region_code}`} className="space-y-2">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <h3 id={`fatigue-${region.region_code}`} className="text-[14px] font-semibold text-ink">{region.region_name}</h3>
                  <p className="type-meta">
                    {region.fatigued} fatigued · {region.watch} watch · {region.healthy} healthy{region.not_enough_data ? ` · ${region.not_enough_data} not enough data` : ""}
                  </p>
                </div>
                <ul className="ledger-rules rounded-card border border-border bg-surface">
                  {[...region.rows]
                    .sort((a, b) => FATIGUE_STATUS[a.status].rank - FATIGUE_STATUS[b.status].rank || a.version_label.localeCompare(b.version_label))
                    .map((row) => (
                      <RowCard key={row.version_label} row={row} campaignId={campaignId} threshold={data.thresholds.frequency_threshold} />
                    ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </Section>
    </PulseTabPage>
  );
}
