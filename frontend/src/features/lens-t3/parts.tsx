"use client";

import { Activity, CircleDashed, ExternalLink, Minus, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";
import { useId } from "react";

import { cn } from "@/lib/utils";

import type { LensMonth, TrendDirection } from "./api";

export const DIRECTION: Record<TrendDirection, { label: string; Icon: LucideIcon; className: string }> = {
  rising: { label: "Rising", Icon: TrendingUp, className: "text-success" },
  falling: { label: "Falling", Icon: TrendingDown, className: "text-danger" },
  steady: { label: "Steady", Icon: Minus, className: "text-ink" },
  mixed: { label: "Mixed", Icon: Activity, className: "text-warning" },
  insufficient: { label: "Not enough data", Icon: CircleDashed, className: "text-ink-secondary" },
};

/** The direction as an icon and a word; the word carries it, colour and icon only reinforce. */
export function DirectionTag({ direction, className }: { direction: TrendDirection; className?: string }) {
  const { label, Icon, className: tone } = DIRECTION[direction];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[13px] font-medium whitespace-nowrap", tone, className)}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {label}
    </span>
  );
}

const pct = new Intl.NumberFormat("en", { signDisplay: "exceptZero", maximumFractionDigits: 0, style: "percent" });
export const percent = (value: number | null | undefined) => (value == null ? "n/a" : pct.format(value));
export const num = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
export const monthName = (ym: string) => new Intl.DateTimeFormat("en", { month: "short", year: "numeric" }).format(new Date(`${ym}-01T00:00:00`));

/**
 * Attention over the series as one line: views per million views of the whole edition, so a fall of the edition does not
 * read as a fall of the article. The last 12 months are shaded; they are what the label compares with the 12 before.
 * Falls back to raw views when the edition's totals were not read.
 */
export function Sparkline({ series, label, width = 132, height = 32 }: { series: LensMonth[]; label: string; width?: number; height?: number }) {
  const id = useId();
  const normalised = series.length > 0 && series.every((p) => p.per_million != null);
  const values = series.map((p) => (normalised ? (p.per_million as number) : p.views));
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const pad = 2;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (values.length - 1);
  const y = (v: number) => height - pad - (v / max) * (height - 2 * pad);
  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const recentFrom = Math.max(0, values.length - 12);
  const first = series[0].month;
  const last = series[series.length - 1].month;
  const unit = normalised ? "views per million edition views" : "views a month";
  const peakAt = values.indexOf(Math.max(...values));
  const text = `${label}: ${unit}, ${monthName(first)} to ${monthName(last)}. Peak ${num.format(values[peakAt])} in ${monthName(series[peakAt].month)}; last month ${num.format(values[values.length - 1])}.`;
  return (
    <svg role="img" aria-labelledby={id} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="shrink-0 overflow-visible text-ink-secondary">
      <title id={id}>{text}</title>
      <rect x={x(recentFrom)} y={0} width={x(values.length - 1) - x(recentFrom) + pad} height={height} fill="currentColor" fillOpacity={0.12} />
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r={2.2} className="fill-ink" />
    </svg>
  );
}

export function SourceChip({ label, url }: { label: string; url: string | null | undefined }) {
  const body = (
    <>
      <span className="truncate">{label}</span>
      {url && <ExternalLink aria-hidden className="size-3 shrink-0" />}
    </>
  );
  const base = "inline-flex max-w-full items-center gap-1 rounded-stamp border border-border px-1.5 py-0.5 text-[12px] text-ink-secondary";
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className={cn(base, "hover:text-ink focus-visible:outline-2 focus-visible:outline-pop")}>
      {body}
    </a>
  ) : (
    <span className={base}>{body}</span>
  );
}
