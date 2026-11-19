"use client";

import { CircleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

import type { UsagePoint } from "./api";
import { axisUsd, formatDay, formatDayLong, num, usd } from "./format";

/** A round axis ceiling: 1, 2 or 5 times a power of ten at or above the largest value. */
export function niceCeil(value: number) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  return ([1, 2, 5, 10].find((m) => m * power >= value) ?? 10) * power;
}

type Kind = "spend" | "calls";

function tooltipLines(p: UsagePoint, kind: Kind) {
  const lines = [formatDayLong(p.day)];
  if (kind === "spend") {
    lines.push(p.calls === 0 ? "No calls" : p.estimated_cost_usd === null ? "Cost not recorded" : `${usd(p.estimated_cost_usd)} estimated`);
    if (p.calls > 0 && p.estimated_cost_usd !== null && p.calls_without_cost > 0) lines.push(`${num.format(p.calls_without_cost)} without a recorded cost`);
  } else {
    lines.push(`${num.format(p.calls)} ${p.calls === 1 ? "call" : "calls"}${p.failed_calls ? `, ${num.format(p.failed_calls)} failed` : ""}`);
  }
  return lines;
}

/**
 * One bar per UTC day. Hover or focus a day for its figures. Spend bars are the recorded estimates; a day with calls but no
 * recorded cost is a dashed stub, never an empty bar. Calls bars stack the failed calls on the succeeded ones, and the
 * legend names both so the two are not told apart by colour alone. The figures are also available as a table.
 */
export function DayBars({ points, kind, title }: { points: UsagePoint[]; kind: Kind; title: string }) {
  const values = points.map((p) => (kind === "spend" ? (p.estimated_cost_usd ?? 0) : p.calls));
  const top = niceCeil(Math.max(0, ...values));
  const step = Math.ceil(points.length / 6);
  const fmt = (n: number) => (kind === "spend" ? axisUsd(n) : num.format(n));
  const total = kind === "spend" ? null : points.reduce((n, p) => n + p.calls, 0);
  return (
    <figure className="min-w-0 space-y-2" aria-label={`${title}, ${points.length} days`}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-[13.5px] font-semibold text-ink">{title}</span>
        {kind === "calls" ? (
          <span className="type-meta flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-[2px] bg-chart-2" />
              Succeeded
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CircleAlert aria-hidden className="size-3 text-danger" />
              <span aria-hidden className="size-2.5 rounded-[2px] bg-danger" />
              Failed
            </span>
          </span>
        ) : (
          <span className="type-meta">Estimated, per UTC day</span>
        )}
      </figcaption>
      <div className="pl-12">
        <div className="relative">
        <span className="type-meta absolute top-0 -left-12 w-11 -translate-y-1/2 text-right">{fmt(top)}</span>
        <span className="type-meta absolute bottom-0 -left-12 w-11 translate-y-1/2 text-right">{fmt(0)}</span>
        <ul className="flex h-36 items-stretch gap-[2px] border-b border-border-strong/60 bg-[linear-gradient(to_bottom,var(--border)_1px,transparent_1px)]">
          {points.map((p, i) => {
            const value = values[i];
            const failed = kind === "calls" ? p.failed_calls : 0;
            const unrecorded = kind === "spend" && p.calls > 0 && p.estimated_cost_usd === null;
            const align = i < points.length / 3 ? "left-0" : i > (points.length * 2) / 3 ? "right-0" : "left-1/2 -translate-x-1/2";
            return (
              <li key={p.day} className="group relative flex min-w-0 flex-1">
                <div
                  tabIndex={0}
                  aria-label={tooltipLines(p, kind).join(". ")}
                  className="flex h-full w-full flex-col-reverse gap-[2px] rounded-t-[3px] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
                >
                  {unrecorded && <span aria-hidden className="mx-auto h-2 w-full max-w-4 rounded-t-[3px] border border-dashed border-ink-muted" />}
                  {kind === "spend" && value > 0 && <span aria-hidden className="w-full rounded-t-[4px] bg-chart-2" style={{ height: `${Math.max(2, (value / top) * 100)}%`, flex: "none" }} />}
                  {kind === "calls" && p.calls - failed > 0 && (
                    <span aria-hidden className={cn("w-full bg-chart-2", failed === 0 && "rounded-t-[4px]")} style={{ height: `${((p.calls - failed) / top) * 100}%`, flex: "none" }} />
                  )}
                  {kind === "calls" && failed > 0 && <span aria-hidden className="w-full rounded-t-[4px] bg-danger" style={{ height: `${Math.max(2, (failed / top) * 100)}%`, flex: "none" }} />}
                </div>
                <span
                  role="tooltip"
                  className={cn(
                    "clay pointer-events-none absolute bottom-full z-10 mb-1 hidden w-max max-w-56 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-ink group-focus-within:block group-hover:block",
                    align,
                  )}
                >
                  {tooltipLines(p, kind).map((l, n) => (
                    <span key={l} className={cn("block", n === 0 ? "font-medium" : "text-ink-secondary")}>
                      {l}
                    </span>
                  ))}
                </span>
              </li>
            );
          })}
        </ul>
        </div>
        <ul aria-hidden className="mt-1 flex h-4 gap-[2px]">
          {points.map((p, i) => (
            <li key={p.day} className="relative min-w-0 flex-1">
              {(i % step === 0 || i === points.length - 1) && (i === points.length - 1 || points.length - 1 - i >= step) && (
                <span className={cn("type-meta absolute top-0 whitespace-nowrap", i === points.length - 1 ? "right-0" : "left-0")}>{formatDay(p.day)}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
      {total !== null && <span className="sr-only">{num.format(total)} calls in total.</span>}
    </figure>
  );
}

/** The same figures as the two charts, for reading, copying and screen readers. */
export function DayTable({ points }: { points: UsagePoint[] }) {
  return (
    <div className="max-h-80 overflow-auto rounded-card border border-border bg-surface">
      <table className="type-ledger w-full min-w-[30rem] text-[13px]">
        <caption className="sr-only">Calls and estimated cost per UTC day</caption>
        <thead className="sticky top-0 bg-surface-muted text-left text-ink-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-normal">Day (UTC)</th>
            <th scope="col" className="px-3 py-2 text-right font-normal">Calls</th>
            <th scope="col" className="px-3 py-2 text-right font-normal">Failed</th>
            <th scope="col" className="px-3 py-2 text-right font-normal">Without a recorded cost</th>
            <th scope="col" className="px-4 py-2 text-right font-normal">Estimated cost</th>
          </tr>
        </thead>
        <tbody className="ledger-rules">
          {[...points].reverse().map((p) => (
            <tr key={p.day}>
              <th scope="row" className="px-4 py-1.5 text-left font-normal text-ink-body">{formatDayLong(p.day)}</th>
              <td className="px-3 py-1.5 text-right">{num.format(p.calls)}</td>
              <td className="px-3 py-1.5 text-right">{num.format(p.failed_calls)}</td>
              <td className="px-3 py-1.5 text-right">{num.format(p.calls_without_cost)}</td>
              <td className="px-4 py-1.5 text-right text-ink">{p.calls === 0 ? "No calls" : usd(p.estimated_cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
