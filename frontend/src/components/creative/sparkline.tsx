"use client";

import { useId, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

import { cn } from "@/lib/utils";

import { roleColor, type RoleKey } from "./motion";

/**
 * Sparkline and MiniArea: a small series you can scrub. Hover (or arrow keys) moves a crosshair and shows a readout of
 * the label and value; Enter or click calls `onSelect(index)` (use it to filter or drill in). The overlay is a
 * `role="slider"`, so keyboard and screen reader users get the same readout.
 *
 *   <Sparkline values={clicks} labels={days} format={(v) => `${v} clicks`} ariaLabel="Clicks per day, last 14 days" />
 *   <MiniArea values={spend} labels={days} tone="pulse" ariaLabel="Spend per day" />
 *
 * Use for real series over time. A single value is not a series; neither is a score dressed up as a trend.
 */
export type SparklineProps = {
  values: number[];
  /** One label per value (dates, weeks, versions). */
  labels?: string[];
  format?: (value: number, index: number) => string;
  ariaLabel: string;
  variant?: "line" | "area";
  /** Ember for the primary series, ink for neutral, or a workspace role. */
  tone?: "pop" | "ink" | RoleKey;
  height?: number;
  onSelect?: (index: number) => void;
  className?: string;
};

const W = 100;

export function Sparkline({ values, labels, format, ariaLabel, variant = "line", tone = "pop", height = 56, onSelect, className }: SparklineProps) {
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const n = values.length;
  if (n === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 6;
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(2)},${height} L${x(0).toFixed(2)},${height} Z`;
  const color = tone === "pop" ? "var(--pop)" : tone === "ink" ? "var(--ink-secondary)" : roleColor(tone, true);
  const show = (i: number) => `${labels?.[i] ? `${labels[i]}: ` : ""}${format ? format(values[i], i) : values[i]}`;
  const at = active ?? n - 1;

  const fromPointer = (e: { clientX: number; currentTarget: HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect();
    return Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1))));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (step) {
      e.preventDefault();
      setActive(Math.max(0, Math.min(n - 1, at + step)));
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      setActive(e.key === "Home" ? 0 : n - 1);
    } else if ((e.key === "Enter" || e.key === " ") && onSelect) {
      e.preventDefault();
      onSelect(at);
    }
  };

  return (
    <div className={cn("relative select-none", className)} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible" aria-hidden>
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {variant === "area" && <path d={area} fill={`url(#${id}-fill)`} />}
        <path d={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {active !== null && <line x1={x(active)} x2={x(active)} y1={0} y2={height} stroke="var(--border-strong)" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />}
      </svg>
      <span
        aria-hidden
        className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface-raised shadow-clay"
        style={{ left: `${x(at)}%`, top: y(values[at]), backgroundColor: color, opacity: active === null && variant === "line" ? 0.85 : 1 }}
      />
      {active !== null && (
        <span
          aria-hidden
          className="pointer-events-none absolute -top-1 z-10 rounded-md bg-surface-raised px-2 py-1 text-[11.5px] whitespace-nowrap text-ink tabular-nums shadow-float"
          style={{ left: `${Math.max(8, Math.min(92, x(active)))}%`, transform: "translate(-50%, -100%)" }}
        >
          {show(active)}
        </span>
      )}
      <div
        role="slider"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={n - 1}
        aria-valuenow={at}
        aria-valuetext={show(at)}
        onPointerMove={(e: ReactPointerEvent<HTMLDivElement>) => setActive(fromPointer(e))}
        onPointerLeave={() => setActive(null)}
        onPointerDown={(e) => setActive(fromPointer(e))}
        onClick={(e) => onSelect?.(fromPointer(e))}
        onFocus={() => setActive(at)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
        className={cn("absolute inset-0 rounded-md focus-visible:outline-offset-4", onSelect ? "cursor-pointer" : "cursor-crosshair")}
      />
    </div>
  );
}

export function MiniArea(props: Omit<SparklineProps, "variant">) {
  return <Sparkline {...props} variant="area" />;
}
