"use client";

import { useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * TimelineRibbon: events on a horizontal ribbon you can scrub. Drag or hover along it (or use the arrow keys) to move the
 * playhead between events; the nearest event lifts and its card shows above the ribbon. Enter or a click on the card
 * calls `onActivate(id)` (open it). Controlled with `value`/`onChange`, or uncontrolled.
 *
 * `scale="time"` spaces events by their timestamps; `"order"` spaces them evenly (use it when events cluster, e.g. a
 * seeded demo where everything happened within seconds). `"auto"` picks order when the span is under six hours.
 *
 *   <TimelineRibbon ariaLabel="What changed, oldest to newest" items={events.map((e) => ({ id: e.id, at: e.at,
 *     label: e.title, detail: e.detail, color: roleColor(e.workspace, true) }))} onActivate={open} />
 */
export type RibbonItem = { id: string; at: string; label: string; detail?: string | null; color?: string; meta?: ReactNode };

export type TimelineRibbonProps = {
  items: RibbonItem[];
  ariaLabel: string;
  value?: string | null;
  onChange?: (id: string) => void;
  onActivate?: (id: string) => void;
  scale?: "time" | "order" | "auto";
  formatAt?: (iso: string) => string;
  className?: string;
};

const SIX_HOURS = 6 * 3600_000;
const defaultAt = (iso: string) => new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

export function TimelineRibbon({ items, ariaLabel, value, onChange, onActivate, scale = "auto", formatAt = defaultAt, className }: TimelineRibbonProps) {
  const sorted = [...items].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const [own, setOwn] = useState<string | null>(null);
  const [scrubbing, setScrubbing] = useState(false);
  const n = sorted.length;
  const first = n ? Date.parse(sorted[0].at) : 0;
  const last = n ? Date.parse(sorted[n - 1].at) : 0;
  const mode = scale === "auto" ? (last - first >= SIX_HOURS ? "time" : "order") : scale;
  const pos = (i: number) => (n <= 1 ? 50 : mode === "time" ? ((Date.parse(sorted[i].at) - first) / (last - first || 1)) * 100 : (i / (n - 1)) * 100);
  const currentId = value !== undefined ? value : own;
  const found = sorted.findIndex((s) => s.id === currentId);
  const index = found >= 0 ? found : n - 1;
  if (n === 0) return null;
  const item = sorted[index];
  const x = pos(index);

  const pick = (i: number) => {
    const id = sorted[Math.max(0, Math.min(n - 1, i))].id;
    if (value === undefined) setOwn(id);
    onChange?.(id);
  };
  const nearest = (e: ReactPointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const k = ((e.clientX - r.left) / r.width) * 100;
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(pos(i) - k) < Math.abs(pos(best) - k)) best = i;
    return best;
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = e.key === "ArrowRight" ? index + 1 : e.key === "ArrowLeft" ? index - 1 : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (next !== null) {
      e.preventDefault();
      pick(next);
    } else if (e.key === "Enter" && onActivate) {
      e.preventDefault();
      onActivate(item.id);
    }
  };

  return (
    <div className={cn("relative pt-18", className)}>
      {/* The card for the event under the playhead; it slides with it (transform only). */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-16 overflow-x-clip">
        <div className="absolute inset-y-0 left-0 w-full transition-transform duration-300 ease-out" style={{ transform: `translateX(${x}%)` }}>
          <div
            className={cn("pointer-events-auto absolute bottom-1 w-[min(19rem,80vw)] rounded-xl bg-surface-raised px-3 py-2 shadow-float", onActivate && "cursor-pointer")}
            style={{ transform: `translateX(${-x}%)` }}
            onClick={() => onActivate?.(item.id)}
          >
            <p className="truncate text-[13px] font-medium text-ink">{item.label}</p>
            <p className="type-meta truncate">
              {formatAt(item.at)}
              {item.detail ? ` · ${item.detail}` : ""}
            </p>
          </div>
        </div>
      </div>

      <div
        role="slider"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-valuemin={1}
        aria-valuemax={n}
        aria-valuenow={index + 1}
        aria-valuetext={`${index + 1} of ${n}: ${item.label}, ${formatAt(item.at)}`}
        onKeyDown={key}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          setScrubbing(true);
          pick(nearest(e));
        }}
        onPointerMove={(e) => {
          if (scrubbing || e.pointerType === "mouse") pick(nearest(e));
        }}
        onPointerUp={() => setScrubbing(false)}
        onPointerCancel={() => setScrubbing(false)}
        className={cn("relative h-10 touch-pan-y overflow-x-clip rounded-full bg-surface-muted/80 shadow-well focus-visible:outline-offset-4", scrubbing ? "cursor-grabbing" : "cursor-ew-resize")}
      >
        <span aria-hidden className="absolute inset-x-4 top-1/2 h-px bg-border-strong/50" />
        <div aria-hidden className="absolute inset-y-0 right-4 left-4">
          {sorted.map((s, i) => (
            <span
              key={s.id}
              className={cn(
                "absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface-raised transition-[scale] duration-200 ease-out",
                i === index && "scale-[1.9] shadow-clay",
              )}
              style={{ left: `${pos(i)}%`, backgroundColor: s.color ?? "var(--ink-muted)" }}
            />
          ))}
          <span className="absolute inset-y-1 left-0 w-full transition-transform duration-300 ease-out" style={{ transform: `translateX(${x}%)` }}>
            <span className="absolute inset-y-0 left-0 w-0.5 -translate-x-1/2 rounded-full bg-pop" />
          </span>
        </div>
      </div>
      <div className="mt-1.5 flex justify-between px-1 text-[11px] text-ink-muted">
        <span>{mode === "time" ? formatAt(sorted[0].at) : "Oldest"}</span>
        <span>{mode === "time" ? formatAt(sorted[n - 1].at) : "Newest"}</span>
      </div>
    </div>
  );
}
