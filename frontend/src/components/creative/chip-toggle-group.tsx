"use client";

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * ChipToggleGroup: 2 to 7 mutually exclusive filters as clay chips, with a raised indicator that wipes from the old
 * choice to the new one (clip-path, no layout). A radio group: arrow keys move and select, Home and End jump. Show a
 * count on every chip and keep an "All" option so the way back is visible.
 *
 *   <ChipToggleGroup ariaLabel="Filter next actions by workspace" value={ws} onChange={setWs}
 *     options={[{ value: "all", label: "All", count: 3 }, { value: "launch", label: "Launch Room", count: 2 }]} />
 *
 * TabInk: the matching ember ink for shadcn line tabs: `<TabsList variant="line" className="relative"><TabInk />…`.
 */
export type ChipOption = { value: string; label: ReactNode; count?: number; icon?: ReactNode };

export type ChipToggleGroupProps = {
  options: ChipOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
};

export function ChipToggleGroup({ options, value, onChange, ariaLabel, size = "md", className }: ChipToggleGroupProps) {
  const group = useRef<HTMLDivElement>(null);
  const ink = useRef<HTMLSpanElement>(null);
  const placed = useRef(false);
  const chips = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, options.findIndex((o) => o.value === value));

  // The indicator is a full-size layer clipped to the selected chip. Measured after layout and on resize, written
  // straight to the style (no re-render); the first placement skips the transition so nothing wipes in on load.
  useLayoutEffect(() => {
    const g = group.current;
    const layer = ink.current;
    if (!g || !layer) return;
    const measure = () => {
      const el = chips.current[index];
      if (!el) return;
      const clip = `inset(${el.offsetTop}px ${g.clientWidth - el.offsetLeft - el.offsetWidth}px ${g.clientHeight - el.offsetTop - el.offsetHeight}px ${el.offsetLeft}px round 999px)`;
      if (!placed.current) {
        layer.style.transition = "none";
        layer.style.clipPath = clip;
        void layer.offsetWidth;
        layer.style.transition = "";
        placed.current = true;
      } else layer.style.clipPath = clip;
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(g);
    return () => ro.disconnect();
  }, [index, options.length]);

  const key = (e: KeyboardEvent<HTMLButtonElement>) => {
    const n = options.length;
    const next = e.key === "ArrowRight" || e.key === "ArrowDown" ? (index + 1) % n : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (index - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (next === null) return;
    e.preventDefault();
    onChange(options[next].value);
    chips.current[next]?.focus();
  };

  return (
    <div ref={group} role="radiogroup" aria-label={ariaLabel} className={cn("relative inline-flex flex-wrap gap-1 rounded-card bg-surface-muted/80 p-1 shadow-well", className)}>
      <span
        ref={ink}
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-card bg-surface-raised transition-[clip-path] duration-200 ease-out"
        style={{ clipPath: "inset(0 100% 100% 0)" }}
      />
      {options.map((o, i) => {
        const on = i === index;
        return (
          <button
            key={o.value}
            ref={(el) => {
              chips.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={key}
            className={cn(
              "relative z-1 inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap transition-colors duration-150",
              size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-8 px-3 text-[13px]",
              on ? "text-ink" : "text-ink-secondary hover:text-ink",
            )}
          >
            {o.icon}
            {o.label}
            {o.count !== undefined && <span className={cn("tabular-nums", on ? "text-pop" : "text-ink-muted")}>{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Ember ink that slides under the active tab of a shadcn `TabsList variant="line"` (give the list `relative`). */
export function TabInk({ className }: { className?: string }) {
  return <TabsPrimitive.Indicator className={cn("tab-ink", className)} />;
}
