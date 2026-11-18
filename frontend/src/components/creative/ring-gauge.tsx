import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

import { roleColor, type RoleKey } from "./motion";

/**
 * RingGauge: a counted fraction as a clay ring, "6 of 8", filling from empty when it first paints. Always a count with
 * its words, never a percentage, and never for confidence or for progress you cannot count.
 *
 *   <RingGauge value={filled} max={8} label="Required brief parts filled" caption="parts" />
 */
export type RingGaugeProps = {
  value: number;
  max: number;
  /** Accessible name, e.g. "Required brief parts filled". Read as "<label>: 6 of 8". */
  label: string;
  /** Small word under the count, e.g. "parts". */
  caption?: ReactNode;
  size?: number;
  tone?: "pop" | "success" | "ink" | RoleKey;
  className?: string;
};

export function RingGauge({ value, max, label, caption, size = 88, tone = "pop", className }: RingGaugeProps) {
  const stroke = Math.max(6, Math.round(size / 10));
  const r = (size - stroke) / 2;
  const length = 2 * Math.PI * r;
  const k = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const color = tone === "pop" ? "var(--pop)" : tone === "success" ? "var(--success)" : tone === "ink" ? "var(--ink)" : roleColor(tone, true);
  return (
    <div role="img" aria-label={`${label}: ${value} of ${max}`} className={cn("relative inline-grid shrink-0 place-items-center", className)} style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-muted)" strokeWidth={stroke} />
        <circle
          className="ring-fill"
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={length}
          strokeDashoffset={length * (1 - k)}
          style={{ "--ring-length": `${length}` } as CSSProperties}
        />
        {/* One notch per counted part (up to 12), so "6 of 8" can be read off the ring itself. */}
        {max > 1 &&
          max <= 12 &&
          Array.from({ length: max }, (_, i) => {
            const a = (i / max) * Math.PI * 2;
            const c = size / 2;
            return (
              <line
                key={i}
                x1={c + Math.cos(a) * (r - stroke / 2 - 1)}
                y1={c + Math.sin(a) * (r - stroke / 2 - 1)}
                x2={c + Math.cos(a) * (r + stroke / 2 + 1)}
                y2={c + Math.sin(a) * (r + stroke / 2 + 1)}
                stroke="var(--surface)"
                strokeWidth={2}
              />
            );
          })}
      </svg>
      <span aria-hidden className="relative flex flex-col items-center leading-none">
        <span className="type-title tabular-nums text-ink" style={{ fontSize: Math.round(size * 0.27) }}>
          {value}
          <span className="text-ink-muted" style={{ fontSize: Math.round(size * 0.16) }}>
            /{max}
          </span>
        </span>
        {caption && <span className="mt-1 text-[10.5px] text-ink-muted">{caption}</span>}
      </span>
    </div>
  );
}
