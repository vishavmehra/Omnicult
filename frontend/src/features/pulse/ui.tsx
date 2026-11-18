"use client";

import { ChevronDown, Clock, FlaskConical, Info } from "lucide-react";
import { useId, type KeyboardEvent, type ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { cn } from "@/lib/utils";

import { NOT_AVAILABLE, NOT_AVAILABLE_WHY, REACH_CAVEAT, SAMPLE_LABEL } from "./logic";

/**
 * Series colours: slots 1 to 4 of the validated categorical palette (dataviz skill, validate_palette.js: all checks pass in
 * both modes on the panel surfaces; in light mode two slots sit under 3:1, so every chart also ships direct labels and a
 * table view). Defined here, on the Pulse root, so the shared stylesheet stays untouched. Colour follows the entity.
 */
export const PULSE_THEME =
  "[--pulse-s1:#2a78d6] [--pulse-s2:#eb6834] [--pulse-s3:#1baf7a] [--pulse-s4:#eda100] dark:[--pulse-s1:#3987e5] dark:[--pulse-s2:#d95926] dark:[--pulse-s3:#199e70] dark:[--pulse-s4:#c98500]";

export const slotColor = (slot: number) => `var(--pulse-s${Math.min(4, Math.max(1, slot))})`;

/** The permanent disclosure: a warning tag with the flask, in capitals, like DEMO DATA. */
export function SampleTag({ className }: { className?: string }) {
  return (
    <Tag className={cn("border-warning/40 bg-warning-soft font-semibold tracking-wide text-warning", className)} title={SAMPLE_LABEL}>
      <FlaskConical aria-hidden />
      SAMPLE DATA
    </Tag>
  );
}

export function ProvisionalTag({ className }: { className?: string }) {
  return (
    <Tag
      className={cn("border-dashed border-ink-secondary/60 bg-surface-muted text-ink-secondary", className)}
      title="Still being reported. Recent conversions arrive days later, so these days read low."
    >
      <Clock aria-hidden />
      Provisional
    </Tag>
  );
}

/** A ratio with no denominator is not available. It is never drawn as 0. */
export function NotAvailable({ className }: { className?: string }) {
  return (
    <span title={NOT_AVAILABLE_WHY} className={cn("text-ink-muted", className)}>
      {NOT_AVAILABLE}
      <span className="sr-only"> (not available: no denominator)</span>
    </span>
  );
}

/** Shown wherever reach, or frequency (derived from it), is shown. */
export function ReachCaveat({ className, text = REACH_CAVEAT }: { className?: string; text?: string }) {
  return (
    <p className={cn("flex max-w-[78ch] items-start gap-1.5 text-[12.5px] leading-snug text-ink-secondary", className)}>
      <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      <span>
        <span className="font-medium text-ink">Reach caveat. </span>
        {text}
      </span>
    </p>
  );
}

/** A section: plain title, optional trailing meta, then its content. Sample label sits in every section's meta. */
export function Section({ id, title, meta, children, className }: { id: string; title: ReactNode; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id={id} className="text-[15px] font-semibold text-ink">
          {title}
        </h2>
        {meta && <div className="type-meta flex flex-wrap items-center gap-x-2 gap-y-1">{meta}</div>}
      </div>
      {children}
    </section>
  );
}

/** Radio-style segmented control: raised clay thumb on a well, arrow keys move the choice. */
export function Segmented<T extends string>({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  value: T | null;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  className?: string;
}) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = options[(i + step + options.length) % options.length];
    onChange(next.value);
    (e.currentTarget.parentElement?.children[(i + step + options.length) % options.length] as HTMLElement | undefined)?.focus();
  };
  const active = options.findIndex((o) => o.value === value);
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex max-w-full flex-wrap gap-0.5 rounded-lg bg-surface-muted p-0.5 shadow-well", className)}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            title={o.title}
            tabIndex={on || (active === -1 && i === 0) ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "h-7 rounded-md px-2.5 text-[13px] whitespace-nowrap transition-[background-color,color,box-shadow] duration-150",
              on ? "bg-surface-raised font-medium text-ink shadow-clay" : "text-ink-secondary hover:text-ink",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const SELECT =
  "h-8 w-full appearance-none rounded-lg border border-input bg-surface-raised pr-8 pl-2.5 text-[13px] text-ink shadow-well transition-colors outline-none focus-visible:border-ring dark:bg-surface-muted";

/** Labelled native select in the Input's clothes. Native keeps keyboard, touch and screen readers correct. */
export function SelectField({
  label,
  value,
  onChange,
  options,
  className,
  hideLabel,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
  hideLabel?: boolean;
}) {
  const id = useId();
  return (
    <div className={cn("space-y-1", className)}>
      <label htmlFor={id} className={cn("block text-[12px] font-medium text-ink-secondary", hideLabel && "sr-only")}>
        {label}
      </label>
      <div className="relative">
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={SELECT}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-ink-muted" />
      </div>
    </div>
  );
}

/** A short line segment in a series colour: the key in legends and tooltips (text never wears the series colour). */
export function LineKey({ slot, className }: { slot: number; className?: string }) {
  return <span aria-hidden className={cn("inline-block h-0.5 w-4 shrink-0 rounded-full", className)} style={{ backgroundColor: slotColor(slot) }} />;
}
