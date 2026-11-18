"use client";

import { Equal, Info, RotateCcw, Repeat, TrendingDown, TrendingUp, CircleDollarSign } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ComponentType } from "react";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { useAlertPreview, useAlertSeries } from "./api";
import {
  ALERT_META, alertEvidence, alertHeadline, classifyCostPattern, DEFAULT_THRESHOLDS, formatSpan, formatValue, parseThresholds, regionLabel, shortVersion,
  type AlertThresholds, type PulseAlert, type SeriesPoint, type ThresholdForm,
} from "./logic";
import { ReachCaveat, SampleTag, Section } from "./ui";

const TYPE_ICON: Record<PulseAlert["alert_type"], ComponentType<{ className?: string }>> = { ctr_drop: TrendingDown, frequency_fatigue: Repeat, cost_spike: CircleDollarSign };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Field({ label, suffix, value, error, onChange, step }: { label: string; suffix: string; value: string; error?: string; onChange: (v: string) => void; step: string }) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[12.5px] font-medium text-ink">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className="w-20 text-right tabular-nums md:text-[13px]"
        />
        <span className="text-[12.5px] text-ink-secondary">{suffix}</span>
      </div>
      {error && (
        <p id={`${id}-error`} role="alert" className="max-w-[28ch] text-[12px] font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** The alert's series in two windows, with the region average as a reference line. Settled days only, as the rule reads them. */
function MiniSeries({ points, average, unit }: { points: SeriesPoint[]; average: number; unit: "cpm" | "cpa"; }) {
  const settled = points.filter((p) => !p.provisional && p.value !== null);
  const W = 360;
  const H = 84;
  const pad = { l: 4, r: 4, t: 14, b: 16 };
  const max = Math.max(average * 1.15, ...settled.map((p) => p.value as number));
  const x = (i: number) => pad.l + (settled.length > 1 ? (i * (W - pad.l - pad.r)) / (settled.length - 1) : 0);
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const d = settled.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.value as number).toFixed(1)}`).join(" ");
  const week = (from: number, to: number) => ({ x: x(from) - 2, w: x(to) - x(from) + 4 });
  const first = week(0, Math.min(6, settled.length - 1));
  const last = week(Math.max(0, settled.length - 7), settled.length - 1);
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${unit.toUpperCase()} per settled day, with the region average of ${formatValue(average, "inr")}.`} className="block h-auto w-full max-w-[24rem]">
        <rect x={first.x} y={pad.t} width={first.w} height={H - pad.t - pad.b} className="fill-ink-muted" opacity={0.1} />
        <rect x={last.x} y={pad.t} width={last.w} height={H - pad.t - pad.b} className="fill-ink-muted" opacity={0.1} />
        <text x={first.x + 3} y={10} className="fill-ink-muted text-[10px]">First week</text>
        <text x={last.x + last.w - 3} y={10} textAnchor="end" className="fill-ink-muted text-[10px]">Last week</text>
        <line x1={pad.l} x2={W - pad.r} y1={y(average)} y2={y(average)} stroke="var(--ink-secondary)" strokeWidth={1} strokeDasharray="4 3" />
        <path d={d} fill="none" stroke="var(--pulse-s1)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {settled.length > 0 && <circle cx={x(settled.length - 1)} cy={y(settled[settled.length - 1].value as number)} r={4} fill="var(--pulse-s1)" stroke="var(--surface)" strokeWidth={2} />}
        <text x={W - pad.r} y={H - 4} textAnchor="end" className="fill-ink-muted text-[10px]">Dashed line: region average {formatValue(average, "inr")}</text>
      </svg>
    </figure>
  );
}

function CostPattern({ campaignId, alert, thresholds, regionName }: { campaignId: string; alert: PulseAlert; thresholds: AlertThresholds; regionName: string }) {
  const q = useMemo(() => new URL(alert.source_path, "http://local").searchParams, [alert.source_path]);
  const series = useAlertSeries(
    campaignId,
    { metric: alert.metric, region: alert.region_code, version: alert.version_label, from: q.get("date_from") ?? alert.window_from, to: q.get("date_to") ?? alert.window_to },
    true,
  );
  if (series.error) return <ErrorState error={series.error} onRetry={() => void series.refetch()} />;
  if (!series.data) return <LoadingState label="Reading the series behind this alert…" className="py-2" />;
  const points = series.data.series[0]?.points ?? [];
  const p = classifyCostPattern(points, alert.comparison_value, thresholds.cost_spike_pct);
  const metric = alert.metric.toUpperCase();
  const money = (v: number | null) => formatValue(v, "inr");
  const pct = (v: number | null) => (v === null ? "" : `${Math.abs(v * 100).toFixed(0)}%`);
  return (
    <div className="grid gap-x-6 gap-y-2 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="space-y-1.5">
        {p.kind === "persistent" && (
          <>
            <Tag className="border-border bg-surface-muted text-ink">
              <Equal aria-hidden />
              Static underperformance, not a spike
            </Tag>
            <p className="max-w-[62ch] text-[13px] leading-snug text-ink-body">
              In its first week this version&apos;s {metric} was already {pct(p.firstVsAverage)} above the {regionName} average (a typical day cost {money(p.firstWeek)} against {money(alert.comparison_value)}),
              and in the last week it was still {pct(p.lastVsAverage)} above ({money(p.lastWeek)} a typical day). The alert fires because the rule compares with the region average, not because the cost jumped.
            </p>
          </>
        )}
        {p.kind === "rising" && (
          <>
            <Tag className="border-warning/30 bg-warning-soft text-warning">
              <TrendingUp aria-hidden />
              Rose during the period
            </Tag>
            <p className="max-w-[62ch] text-[13px] leading-snug text-ink-body">
              In its first week this version&apos;s {metric} was within the {pct(thresholds.cost_spike_pct)} threshold of the {regionName} average (a typical day cost {money(p.firstWeek)} against {money(alert.comparison_value)}),
              then climbed to {money(p.lastWeek)} in the last week. That is a rise, not a standing gap.
            </p>
          </>
        )}
        {p.kind === "unknown" && (
          <p className="max-w-[62ch] text-[13px] leading-snug text-ink-secondary">Fewer than 14 settled days, so a rise cannot be told from a standing gap.</p>
        )}
      </div>
      {p.kind !== "unknown" && <MiniSeries points={points} average={alert.comparison_value} unit={alert.metric as "cpm" | "cpa"} />}
    </div>
  );
}

function AlertRow({ campaignId, alert, thresholds, names }: { campaignId: string; alert: PulseAlert; thresholds: AlertThresholds; names: Record<string, string> }) {
  const Icon = TYPE_ICON[alert.alert_type];
  const meta = ALERT_META[alert.alert_type];
  const region = regionLabel(alert.region_code, names);
  return (
    <li className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Tag className="border-border bg-surface-muted text-ink" title={meta.rule}>
          <Icon aria-hidden />
          {meta.label}
        </Tag>
        <p className="text-[13px] text-ink-body">
          <span className="font-medium text-ink">{region}</span> · <span title={alert.version_label}>{shortVersion(alert.version_label)}</span>
        </p>
        <p className="type-meta sm:ml-auto">
          Window {formatSpan(alert.window_from, alert.window_to)}
        </p>
      </div>
      <div className="space-y-0.5">
        <p className="text-[14px] font-semibold text-ink">{alertHeadline(alert, region)}</p>
        <p className="text-[13px] text-ink-secondary">{alertEvidence(alert)}</p>
      </div>
      {alert.alert_type === "cost_spike" ? (
        <CostPattern campaignId={campaignId} alert={alert} thresholds={thresholds} regionName={region} />
      ) : (
        <div className="space-y-1.5">
          <p className="max-w-[62ch] text-[13px] leading-snug text-ink-secondary">
            Measured against this version&apos;s own first week, so it reads wear-out over time. It does not compare the version with the others.
          </p>
          {alert.alert_type === "frequency_fatigue" && <ReachCaveat className="text-[12px]" />}
        </div>
      )}
      <p className="text-[13px] text-ink-body">
        <span className="font-medium text-ink">Suggested action: </span>
        {alert.suggested_action}
      </p>
    </li>
  );
}

const RULE_NAME: Record<string, string> = { all: "All rules", ctr_drop: "CTR drop", frequency_fatigue: "Frequency fatigue", "cost_spike:cpa": "Cost spike on CPA", "cost_spike:cpm": "Cost spike on CPM" };

/** Alert preview: three deterministic rules over settled days, thresholds editable, nothing saved or sent. */
export function AlertsSection({ campaignId, names }: { campaignId: string; names: Record<string, string> }) {
  const [form, setForm] = useState<ThresholdForm>(DEFAULT_THRESHOLDS);
  const parsed = parseThresholds(form);
  const debounced = useDebounced(form, 350);
  const settled = parseThresholds(debounced);
  const preview = useAlertPreview(campaignId, settled.ok ? settled.query : null);
  const data = preview.data;
  const set = (k: keyof ThresholdForm) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const errors = parsed.ok ? {} : parsed.errors;
  const dirty = JSON.stringify(form) !== JSON.stringify(DEFAULT_THRESHOLDS);

  return (
    <Section
      id="alerts"
      title="Alert preview"
      meta={
        <>
          <SampleTag />
          <span>Preview of Alerts, a roadmap feature</span>
        </>
      }
    >
      <p className="flex max-w-[78ch] items-start gap-1.5 text-[13px] leading-snug text-ink-body">
        <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-ink-secondary" />
        <span>
          <span className="font-medium text-ink">Nothing is saved or sent. </span>
          These thresholds exist only in this preview and return to their defaults when you reload. Three fixed rules read the sample&apos;s settled days; provisional days are never used.
        </span>
      </p>
      <div className="rounded-card border border-border bg-surface px-4 py-4">
        <fieldset className="space-y-3">
          <legend className="sr-only">Alert thresholds</legend>
          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="CTR drop alert" suffix="% below the first week" step="1" value={form.ctrDropPct} onChange={set("ctrDropPct")} error={errors.ctrDropPct} />
            <Field label="Frequency fatigue alert at" suffix="× or more" step="0.1" value={form.frequency} onChange={set("frequency")} error={errors.frequency} />
            <Field label="And CTR at least" suffix="% below the first week" step="1" value={form.frequencyCtrPct} onChange={set("frequencyCtrPct")} error={errors.frequencyCtrPct} />
            <Field label="Cost spike alert" suffix="% above the region average" step="5" value={form.costSpikePct} onChange={set("costSpikePct")} error={errors.costSpikePct} />
            <Field label="CPA needs at least" suffix="conversions in the week" step="1" value={form.minConversions} onChange={set("minConversions")} error={errors.minConversions} />
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
            <Button variant="outline" size="sm" disabled={!dirty} onClick={() => setForm(DEFAULT_THRESHOLDS)}>
              <RotateCcw aria-hidden />
              Reset to defaults
            </Button>
            <p className="type-meta">The preview updates as you type. Out-of-range values are not sent.</p>
          </div>
        </fieldset>
        <dl className="mt-4 grid gap-x-8 gap-y-2 border-t border-border pt-3 text-[12.5px] sm:grid-cols-3">
          {Object.values(ALERT_META).map((m) => (
            <div key={m.label}>
              <dt className="font-medium text-ink">{m.label}</dt>
              <dd className="text-ink-secondary">{m.rule}</dd>
            </div>
          ))}
        </dl>
      </div>

      {preview.error && !data ? (
        <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
      ) : !data ? (
        parsed.ok ? <LoadingState label="Running the alert rules…" /> : <p className="text-[13px] text-ink-secondary">Fix the highlighted thresholds to run the preview.</p>
      ) : (
        <div className={cn("space-y-3 transition-opacity", preview.isPlaceholderData && "opacity-60")} aria-busy={preview.isPlaceholderData}>
          <p className="type-ledger text-[13px] text-ink-body" aria-live="polite">
            <span className="font-semibold text-ink">
              {data.alerts.length} {data.alerts.length === 1 ? "alert" : "alerts"}
            </span>{" "}
            from {data.evaluated} version and region pairs with enough settled data
            {data.skipped.length > 0 ? `; ${data.skipped.length} not evaluated` : ""}.
          </p>
          {data.alerts.length === 0 ? (
            <EmptyState title="No alerts at these thresholds" description="Loosen a threshold to see what the rules would have flagged. Nothing was hidden: every pair with enough settled data was evaluated." />
          ) : (
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {data.alerts.map((a) => (
                <AlertRow key={`${a.alert_type}-${a.region_code}-${a.version_label}-${a.metric}`} campaignId={campaignId} alert={a} thresholds={data.thresholds} names={names} />
              ))}
            </ul>
          )}
          {data.skipped.length > 0 && (
            <div className="rounded-lg border border-border bg-surface-muted px-3.5 py-2.5">
              <p className="text-[12.5px] font-semibold text-ink">Not evaluated</p>
              <p className="text-[12.5px] text-ink-secondary">A rule that cannot run is listed here with its reason. It is not read as &quot;no alert&quot;.</p>
              <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-body marker:text-ink-secondary">
                {data.skipped.map((s, i) => (
                  <li key={i}>
                    {regionLabel(s.region_code, names)}, {shortVersion(s.version_label)}: {RULE_NAME[s.rule] ?? s.rule}. {s.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="type-meta">{data.note}</p>
        </div>
      )}
    </Section>
  );
}
