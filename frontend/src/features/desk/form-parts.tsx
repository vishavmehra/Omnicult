"use client";

import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** Native select with the chevron the other forms use. */
export function Select({
  id,
  value,
  onChange,
  children,
  className,
  disabled,
  label,
}: {
  id?: string;
  value: string;
  onChange(value: string): void;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <span className={cn("relative block", className)}>
      <select
        id={id}
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 w-full appearance-none rounded-lg border border-input bg-surface pr-8 pl-2.5 text-sm text-ink outline-none focus-visible:border-ring disabled:opacity-60"
      >
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-ink-secondary" />
    </span>
  );
}

/** A pressable choice that stays visible as selected (aria-pressed). Used where several can be on. */
export function ToggleChip({ pressed, onClick, children, title }: { pressed: boolean; onClick(): void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      title={title}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center rounded-lg border px-2.5 text-[13px] transition-colors",
        pressed ? "clay border-border font-medium text-ink" : "border-border text-ink-secondary hover:bg-surface-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** One entry per line. Blank lines are dropped from the value, not from what you are typing. */
export function Lines({
  id,
  value,
  onChange,
  rows = 3,
  placeholder,
  disabled,
}: {
  id: string;
  value: string[];
  onChange(next: string[]): void;
  rows?: number;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState(value.join("\n"));
  return (
    <Textarea
      id={id}
      rows={rows}
      value={text}
      disabled={disabled}
      placeholder={placeholder}
      className="bg-surface"
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split("\n").map((l) => l.trim()).filter(Boolean));
      }}
    />
  );
}

/** A repeatable group of rows with Add and Remove. `render` draws one row's fields. */
export function Repeater<T>({
  items,
  onChange,
  make,
  render,
  addLabel,
  noun,
  max,
  empty,
}: {
  items: T[];
  onChange(next: T[]): void;
  make(): T;
  render(item: T, set: (patch: Partial<T>) => void, index: number): ReactNode;
  addLabel: string;
  noun: string;
  max?: number;
  empty?: string;
}) {
  return (
    <div className="space-y-2.5">
      {items.length === 0 && empty && <p className="text-[13px] text-ink-muted">{empty}</p>}
      <ul className="space-y-2.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 rounded-lg border border-border bg-surface-muted/60 p-3">
            <div className="min-w-0 flex-1">{render(item, (patch) => onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x))), i)}</div>
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${noun} ${i + 1}`} onClick={() => onChange(items.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
      <Button type="button" variant="outline" size="sm" disabled={max !== undefined && items.length >= max} onClick={() => onChange([...items, make()])}>
        <Plus aria-hidden />
        {addLabel}
      </Button>
    </div>
  );
}

/** A titled group inside a form. */
export function Group({ legend, hint, children }: { legend: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="space-y-3.5 rounded-card border border-border bg-surface p-4 sm:p-5">
      <legend className="px-1 text-[15px] font-semibold text-ink">{legend}</legend>
      {hint && <p className="-mt-1 max-w-prose text-[12.5px] text-ink-secondary">{hint}</p>}
      {children}
    </fieldset>
  );
}

/** What the server rejected, in its own words, so a failed save never looks like a silent one. */
export function ServerProblems({ errors }: { errors: Record<string, string> }) {
  const entries = Object.entries(errors).filter(([, message]) => message);
  if (!entries.length) return null;
  return (
    <div role="alert" className="space-y-1 rounded-lg border border-danger/35 bg-danger-soft/60 px-4 py-3 text-[13px] text-ink">
      <p className="font-medium text-danger">The API did not accept this version. Nothing was saved.</p>
      <ul className="list-disc space-y-0.5 pl-5">
        {entries.map(([field, message]) => (
          <li key={field}>
            {field ? <span className="font-mono text-[11.5px] text-ink-secondary">{field.replace(/^content\.|^design\./, "")}: </span> : null}
            {message}
          </li>
        ))}
      </ul>
    </div>
  );
}
