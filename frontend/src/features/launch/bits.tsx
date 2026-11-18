"use client";

import { ChevronRight, CircleDashed, Database, PencilLine } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { GROUP_LABEL, GROUPS, groupState, type Draft, type GroupKey, type GroupState } from "./observations";

/** Sheet width: the default sheet sets width and max-width through a data-side variant, so the override must use the same variant. */
export const WIDE_SHEET = "data-[side=right]:w-full data-[side=right]:sm:max-w-2xl";

/** A native select: the standard affordance, styled as the other form controls. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 w-full min-w-0 rounded-lg border border-input bg-surface-raised px-2 text-[14px] text-ink shadow-well transition-colors outline-none focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 dark:bg-surface-muted",
        className,
      )}
      {...props}
    />
  );
}

/** A whole-number field. The text stays a string while it is typed; the conversion and its errors live in observations.ts. */
export function NumField({ id, label, value, onChange, className }: { id: string; label: ReactNode; value: string; onChange(v: string): void; className?: string }) {
  return (
    <div className={cn("min-w-0 space-y-1", className)}>
      <label htmlFor={id} className="block text-[12.5px] text-ink-secondary">
        {label}
      </label>
      <Input id={id} inputMode="numeric" autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)} className="tabular-nums" />
    </div>
  );
}

/** Missing, entered or gathered: an icon, a word and a tone, never colour alone. */
export function InputStatusChip({ state }: { state: GroupState }) {
  if (state.state === "gathered") {
    return (
      <Tag className="border-info/30 bg-info-soft text-info" title={`${state.source}, read ${formatDateTime(state.at)}`}>
        <Database aria-hidden />
        Gathered
      </Tag>
    );
  }
  if (state.state === "entered") {
    return (
      <Tag className="border-border bg-surface-muted text-ink" title={state.at ? `Entered ${formatDateTime(state.at)}` : undefined}>
        <PencilLine aria-hidden />
        Entered here
      </Tag>
    );
  }
  return (
    <Tag className="border-dashed border-warning/60 bg-warning-soft text-warning" title="Not supplied. The rules report it as missing and never assume a value.">
      <CircleDashed aria-hidden />
      Missing
    </Tag>
  );
}

/** One line per observation group with its state: the at-a-glance answer to "what do the rules have to work with?" */
export function InputSummary({ draft, only, className }: { draft: Draft; only?: GroupKey[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1.5", className)} aria-label="Observation inputs">
      {(only ?? GROUPS).map((g) => (
        <li key={g} className="inline-flex items-center gap-1.5 text-[12.5px]">
          <span className="text-ink-secondary">{GROUP_LABEL[g]}</span>
          <InputStatusChip state={groupState(draft, g)} />
        </li>
      ))}
    </ul>
  );
}

/** A number the rules computed, shown to one decimal with a tabular figure (a value out of 100, never a percentage of anything). */
export const points = (value: number | null | undefined) => (value === null || value === undefined ? "n/a" : value.toFixed(1));

/** A native disclosure with a rotating chevron: titled, counted, closed unless told otherwise. */
export function Disclosure({ title, count, defaultOpen, className, children }: { title: ReactNode; count?: ReactNode; defaultOpen?: boolean; className?: string; children: ReactNode }) {
  return (
    <details open={defaultOpen} className={cn("group border-t border-border", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-2.5 text-[13.5px] font-medium text-ink hover:bg-surface-muted/50 [&::-webkit-details-marker]:hidden">
        <ChevronRight aria-hidden className="size-4 shrink-0 text-ink-muted transition-transform duration-200 group-open:rotate-90 motion-reduce:transition-none" />
        {title}
        {count !== undefined && <span className="type-meta">{count}</span>}
      </summary>
      <div className="px-5 pb-4">{children}</div>
    </details>
  );
}
