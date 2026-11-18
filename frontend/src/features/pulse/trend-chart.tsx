"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { cn } from "@/lib/utils";

import { formatDay, formatDayLong, formatTick, formatValue, formatWeekday, niceTicks, type SeriesPoint, type Unit } from "./logic";
import { LineKey, NotAvailable, ProvisionalTag, slotColor } from "./ui";

export type ChartSeries = { key: string; label: string; slot: number; points: SeriesPoint[] };

type Pt = { x: number; y: number; v: number; prov: boolean; i: number };

/** Consecutive points become runs; a run is dashed when it ends on a provisional day, so the line itself says "still moving". */
function runs(pts: (Pt | null)[]) {
  const out: { dashed: boolean; pts: Pt[] }[] = [];
  let cur: { dashed: boolean; pts: Pt[] } | null = null;
  for (const p of pts) {
    if (!p) {
      cur = null;
      continue;
    }
    if (!cur) {
      cur = { dashed: p.prov, pts: [p] };
      out.push(cur);
    } else if (cur.dashed === p.prov) {
      cur.pts.push(p);
    } else {
      cur = { dashed: p.prov, pts: [cur.pts[cur.pts.length - 1], p] };
      out.push(cur);
    }
  }
  return out.map((r) => ({ dashed: r.dashed, d: r.pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") }));
}

/**
 * Daily lines in plain SVG: 2px strokes, hairline grid, zero-based axis, an end dot with a surface ring, a crosshair that
 * snaps to the day, one tooltip listing every series (also on arrow keys), and a data table twin. Provisional days sit in a
 * shaded band with dashed lines and hollow dots. Scales are linear and start at zero; nothing is smoothed.
 */
export function TrendChart({ series, unit, description, stale }: { series: ChartSeries[]; unit: Unit; description: string; stale?: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(260, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const model = useMemo(() => {
    const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.date)))].sort();
    const values = series.flatMap((s) => s.points.flatMap((p) => (p.value === null ? [] : [p.value])));
    const ticks = niceTicks(Math.max(0, ...values));
    return { dates, ticks, top: ticks[ticks.length - 1] || 1 };
  }, [series]);

  const H = width < 480 ? 240 : 280;
  const tickLabels = model.ticks.map((t) => formatTick(t, unit));
  const left = Math.max(...tickLabels.map((t) => t.length)) * 6.6 + 16;
  const labelsOn = width >= 560 && series.length <= 4;
  const right = labelsOn ? 66 : 14;
  const top = 26;
  const bottom = 28;
  const plotW = Math.max(40, width - left - right);
  const plotH = H - top - bottom;
  const n = model.dates.length;
  const stepPx = n > 1 ? plotW / (n - 1) : plotW;
  const xAt = (i: number) => left + (n > 1 ? i * stepPx : plotW / 2);
  const yAt = (v: number) => top + plotH - (v / model.top) * plotH;

  const lines = series.map((s) => {
    const byDate = new Map(s.points.map((p) => [p.date, p]));
    const pts = model.dates.map((d, i): Pt | null => {
      const p = byDate.get(d);
      return p && p.value !== null ? { x: xAt(i), y: yAt(p.value), v: p.value, prov: p.provisional, i } : null;
    });
    return { s, pts, runs: runs(pts), last: [...pts].reverse().find(Boolean) ?? null };
  });

  const firstProv = model.dates.findIndex((d) => series.some((s) => s.points.some((p) => p.date === d && p.provisional)));
  const bandX = firstProv === -1 ? null : Math.max(left, xAt(firstProv) - stepPx / 2);

  // End labels only when they do not collide: nudging them apart would detach them from their lines.
  const ends = lines.flatMap((l) => (l.last ? [l.last.y] : [])).sort((a, b) => a - b);
  const labelsClear = labelsOn && ends.every((y, i) => i === 0 || y - ends[i - 1] >= 14);

  const every = Math.max(1, Math.ceil(64 / stepPx));
  const hover = (clientX: number, svg: SVGSVGElement) => {
    const x = clientX - svg.getBoundingClientRect().left;
    setActive(Math.min(n - 1, Math.max(0, Math.round((x - left) / stepPx))));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const cur = active ?? n - 1;
    const next = e.key === "ArrowLeft" ? cur - 1 : e.key === "ArrowRight" ? cur + 1 : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : e.key === "Escape" ? -2 : null;
    if (next === null) return;
    e.preventDefault();
    setActive(next === -2 ? null : Math.min(n - 1, Math.max(0, next)));
  };

  const activeDate = active === null ? null : model.dates[active];
  const tipRows = activeDate
    ? lines.flatMap((l) => {
        const p = l.s.points.find((q) => q.date === activeDate);
        return p ? [{ l, p }] : [];
      })
    : [];
  const tipProvisional = tipRows.some((r) => r.p.provisional);
  const flip = active !== null && xAt(active) > width * 0.58;

  return (
    <div className="space-y-3">
      {series.length >= 2 && (
        <ul aria-label="Legend" className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-secondary">
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <LineKey slot={s.slot} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <div
        ref={wrap}
        tabIndex={0}
        role="group"
        aria-label={`${description} Use the left and right arrow keys to read each day.`}
        onKeyDown={onKey}
        onFocus={() => setActive((a) => a ?? n - 1)}
        onBlur={() => setActive(null)}
        className={cn("relative rounded-lg transition-opacity", stale && "opacity-60")}
        aria-busy={stale}
      >
        <svg width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={description} className="block max-w-full tabular-nums">
          {model.ticks.map((t, i) => (
            <g key={t}>
              <line x1={left} x2={left + plotW} y1={yAt(t)} y2={yAt(t)} stroke="var(--border)" strokeWidth={1} opacity={t === 0 ? 1 : 0.7} />
              <text x={left - 8} y={yAt(t)} dy="0.32em" textAnchor="end" className="fill-ink-muted text-[11px]">
                {tickLabels[i]}
              </text>
            </g>
          ))}
          {bandX !== null && (
            <g>
              <rect x={bandX} y={top} width={left + plotW - bandX + 0.5} height={plotH} className="fill-ink-muted" opacity={0.13} />
              <text x={left + plotW} y={top - 8} textAnchor="end" className="fill-ink-secondary text-[11px] font-medium">
                Provisional days
              </text>
            </g>
          )}
          {model.dates.map((d, i) =>
            i % every === 0 ? (
              <text key={d} x={xAt(i)} y={H - 8} textAnchor="middle" className="fill-ink-muted text-[11px]">
                {formatDay(d)}
              </text>
            ) : null,
          )}
          {activeDate !== null && active !== null && <line x1={xAt(active)} x2={xAt(active)} y1={top} y2={top + plotH} stroke="var(--border-strong)" strokeWidth={1} />}
          {lines.map(({ s, runs: rs }) => (
            <g key={s.key}>
              {rs.map((r, i) => (
                <path key={i} d={r.d} fill="none" stroke={slotColor(s.slot)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={r.dashed ? "5 4" : undefined} />
              ))}
            </g>
          ))}
          {lines.map(({ s, pts, last }) => (
            <g key={s.key}>
              {pts.map((p) =>
                p && p.prov && p !== last ? <circle key={p.i} cx={p.x} cy={p.y} r={3} fill="var(--surface)" stroke={slotColor(s.slot)} strokeWidth={2} /> : null,
              )}
              {last && (
                <circle
                  cx={last.x}
                  cy={last.y}
                  r={4}
                  fill={last.prov ? "var(--surface)" : slotColor(s.slot)}
                  stroke={last.prov ? slotColor(s.slot) : "var(--surface)"}
                  strokeWidth={2}
                />
              )}
              {labelsClear && last && (
                <text x={last.x + 10} y={last.y} dy="0.32em" className="fill-ink text-[11.5px] font-medium">
                  {formatValue(last.v, unit, { compact: true })}
                </text>
              )}
            </g>
          ))}
          {active !== null &&
            tipRows.map(({ l, p }) => {
              const pt = l.pts[active];
              return pt ? (
                <circle key={l.s.key} cx={pt.x} cy={pt.y} r={4.5} fill={p.provisional ? "var(--surface)" : slotColor(l.s.slot)} stroke={p.provisional ? slotColor(l.s.slot) : "var(--surface)"} strokeWidth={2} />
              ) : null;
            })}
          <rect
            x={left}
            y={top}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerMove={(e: PointerEvent<SVGRectElement>) => e.currentTarget.ownerSVGElement && hover(e.clientX, e.currentTarget.ownerSVGElement)}
            onPointerLeave={() => document.activeElement !== wrap.current && setActive(null)}
          />
        </svg>
        {active !== null && activeDate && (
          <div
            aria-live="polite"
            className="pointer-events-none absolute z-10 w-max max-w-[17rem] rounded-lg border border-border bg-surface-raised px-3 py-2 text-[12.5px] shadow-float"
            style={{ top: top + 4, ...(flip ? { right: width - xAt(active) + 12 } : { left: xAt(active) + 12 }) }}
          >
            <p className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-secondary">
              <span>
                {formatWeekday(activeDate)} {formatDayLong(activeDate)}
              </span>
              {tipProvisional && <ProvisionalTag />}
            </p>
            <ul className="space-y-1">
              {tipRows.map(({ l, p }) => (
                <li key={l.s.key} className="flex items-center gap-2">
                  <LineKey slot={l.s.slot} />
                  <span className="font-semibold text-ink tabular-nums">{p.value === null ? <NotAvailable /> : formatValue(p.value, unit)}</span>
                  {series.length > 1 && <span className="text-ink-secondary">{l.s.label}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <details className="group text-[12.5px]">
        <summary className="inline-flex cursor-pointer items-center gap-1.5 text-ink-secondary hover:text-ink">Data table</summary>
        <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-border">
          <table className="type-ledger w-full min-w-[22rem] text-left text-[12.5px]">
            <caption className="sr-only">{description}</caption>
            <thead className="sticky top-0 bg-surface-muted text-ink-secondary">
              <tr>
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Day
                </th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="px-3 py-1.5 text-right font-medium">
                    {s.label}
                  </th>
                ))}
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {model.dates.map((d) => {
                const prov = series.some((s) => s.points.some((p) => p.date === d && p.provisional));
                return (
                  <tr key={d}>
                    <th scope="row" className="px-3 py-1.5 font-normal text-ink">
                      {formatWeekday(d)} {formatDayLong(d)}
                    </th>
                    {series.map((s) => {
                      const p = s.points.find((q) => q.date === d);
                      return (
                        <td key={s.key} className="px-3 py-1.5 text-right text-ink tabular-nums">
                          {p && p.value !== null ? formatValue(p.value, unit) : <NotAvailable />}
                        </td>
                      );
                    })}
                    <td className="px-3 py-1.5 text-ink-secondary">{prov ? "Provisional" : "Settled"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
