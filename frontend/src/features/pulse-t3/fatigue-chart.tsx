"use client";

import { addDays, formatDay, formatTick, niceTicks } from "@/features/pulse/logic";

import { linePaths, plot, WINDOW_DAYS, type FatiguePoint } from "./logic";

const W = 300;
const H = 104;
const PAD = { l: 6, r: 6, t: 16, b: 20 };

/**
 * One metric of one version in one region, day by day, on a zero-based axis. The first week and the last settled week that the
 * fatigue signals compare are shaded; provisional days continue as a dashed line. The first and last settled values are labelled
 * directly, and the figures behind them are in the signal table beside the chart.
 */
export function FatigueChart({
  title, unit, points, from, to, slot, threshold, thresholdLabel,
}: {
  title: string;
  unit: "ratio" | "multiple";
  points: FatiguePoint[];
  from: string | null;
  to: string | null;
  slot: 1 | 2;
  threshold?: number | null;
  thresholdLabel?: string;
}) {
  const { points: plotted, max, x, y } = plot(points, W, H, PAD, threshold ?? 0);
  const { settled: solid, provisional: dashed } = linePaths(plotted);
  const settled = points.map((p, i) => ({ p, i })).filter(({ p }) => p.value !== null && !p.provisional);
  const first = settled[0];
  const last = settled[settled.length - 1];
  const index = (iso: string) => points.findIndex((p) => p.date === iso);
  const band = (a: string | null, b: string | null) => {
    if (!a || !b || index(a) < 0 || index(b) < 0) return null;
    return { x: x(index(a)) - 2, w: Math.max(4, x(index(b)) - x(index(a)) + 4) };
  };
  const firstBand = band(from, from ? addDays(from, WINDOW_DAYS - 1) : null);
  const lastBand = band(to ? addDays(to, -(WINDOW_DAYS - 1)) : null, to);
  const color = `var(--pulse-s${slot})`;
  const ticks = niceTicks(max / 1.1, 3).filter((t) => t > 0 && t <= max);
  const label =
    first && last
      ? `${title}: ${formatTick(first.p.value as number, unit)} on ${formatDay(first.p.date)}, ${formatTick(last.p.value as number, unit)} on ${formatDay(last.p.date)}.`
      : `${title}: no values.`;

  return (
    <figure className="space-y-1">
      <figcaption className="text-[12px] font-medium text-ink-secondary">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="block h-auto w-full max-w-[22rem]">
        {firstBand && <rect x={firstBand.x} y={PAD.t} width={firstBand.w} height={H - PAD.t - PAD.b} className="fill-ink-muted" opacity={0.1} />}
        {lastBand && <rect x={lastBand.x} y={PAD.t} width={lastBand.w} height={H - PAD.t - PAD.b} className="fill-ink-muted" opacity={0.1} />}
        {firstBand && <text x={firstBand.x + 3} y={10} className="fill-ink-muted text-[9.5px]">First week</text>}
        {lastBand && <text x={lastBand.x + lastBand.w - 3} y={10} textAnchor="end" className="fill-ink-muted text-[9.5px]">Last week</text>}
        <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} stroke="var(--border-strong)" strokeWidth={1} />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={W - PAD.r} y={y(t) - 2} textAnchor="end" className="fill-ink-muted text-[9px]">{formatTick(t, unit)}</text>
          </g>
        ))}
        {threshold ? (
          <g>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(threshold)} y2={y(threshold)} stroke="var(--ink-secondary)" strokeWidth={1} strokeDasharray="4 3" />
            <text x={PAD.l + 2} y={y(threshold) - 3} className="fill-ink-secondary text-[9.5px]">{thresholdLabel}</text>
          </g>
        ) : null}
        <path d={solid} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {dashed && <path d={dashed} fill="none" stroke={color} strokeWidth={2} strokeDasharray="3 3" strokeLinecap="round" opacity={0.7} />}
        {first && last && (
          <>
            <circle cx={x(first.i)} cy={y(first.p.value as number)} r={3} fill={color} stroke="var(--surface)" strokeWidth={1.5} />
            <circle cx={x(last.i)} cy={y(last.p.value as number)} r={3.5} fill={color} stroke="var(--surface)" strokeWidth={1.5} />
            <text x={x(first.i) + 5} y={y(first.p.value as number) - 6} className="fill-ink text-[10px] font-medium">{formatTick(first.p.value as number, unit)}</text>
            <text x={x(last.i) - 5} y={y(last.p.value as number) - 7} textAnchor="end" className="fill-ink text-[10px] font-medium">{formatTick(last.p.value as number, unit)}</text>
          </>
        )}
        <text x={PAD.l} y={H - 5} className="fill-ink-muted text-[9.5px]">{points.length ? formatDay(points[0].date) : ""}</text>
        <text x={W - PAD.r} y={H - 5} textAnchor="end" className="fill-ink-muted text-[9.5px]">{points.length ? formatDay(points[points.length - 1].date) : ""}</text>
      </svg>
    </figure>
  );
}
