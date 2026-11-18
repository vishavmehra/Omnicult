"use client";

import { ChevronDown, Play } from "lucide-react";
import { useId, type ReactNode } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { ChipSelect, ListPicker } from "./lab-parts";
import { CITY_TIER_LABEL } from "./labels";
import type { RunKind, SamplingOptions, SamplingPlan } from "./types";

export type Dimensions = { languages: string[]; cityTiers: string[]; ageBands: string[] };
export const NO_DIMENSIONS: Dimensions = { languages: [], cityTiers: [], ageBands: [] };

/** Only dimensions the person narrowed are sent; the server fills the rest with its documented defaults. */
export function toPlan(d: Dimensions, states?: string[]): SamplingPlan {
  const plan: SamplingPlan = {};
  if (states?.length) plan.states = states;
  if (d.languages.length) plan.languages = d.languages;
  if (d.cityTiers.length) plan.city_tiers = d.cityTiers as NonNullable<SamplingPlan["city_tiers"]>;
  if (d.ageBands.length) plan.age_bands = d.ageBands as NonNullable<SamplingPlan["age_bands"]>;
  return plan;
}

/** Language, city tier and age band: the dimensions a panel may be sampled by besides the state. */
export function SamplingDimensions({ options, value, onChange, languageHint }: { options: SamplingOptions; value: Dimensions; onChange(next: Dimensions): void; languageHint: string }) {
  const id = useId();
  return (
    <div className="space-y-4">
      <ListPicker
        id={`${id}-lang`}
        label="Languages"
        placeholder="Add a language"
        options={options.languages.map((l) => ({ value: l.code, label: l.name }))}
        value={value.languages}
        onChange={(languages) => onChange({ ...value, languages })}
        max={6}
        hint={languageHint}
      />
      <ChipSelect
        legend="City tiers"
        hint="None selected means every tier."
        options={options.city_tiers.map((t) => ({ value: t, label: CITY_TIER_LABEL[t] ?? t }))}
        value={value.cityTiers}
        onChange={(cityTiers) => onChange({ ...value, cityTiers })}
      />
      <ChipSelect
        legend="Age bands"
        hint="None selected means every band."
        options={options.age_bands.map((a) => ({ value: a, label: a }))}
        value={value.ageBands}
        onChange={(ageBands) => onChange({ ...value, ageBands })}
      />
      <p className="max-w-prose text-xs text-ink-secondary">
        Panels are sampled only by state, language, city tier and age band. The server refuses to sample by {options.protected_traits.join(", ")}; they are not offered here.
      </p>
    </div>
  );
}

/** A clay panel whose header toggles the form open, so an earlier result stays the first thing on the page. */
export function SetupPanel({ title, meta, open, onOpenChange, children }: { title: string; meta?: ReactNode; open: boolean; onOpenChange(next: boolean): void; children: ReactNode }) {
  const id = useId();
  return (
    <section className="rounded-card border border-border bg-surface">
      <h3 className="text-[14px] font-semibold text-ink">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => onOpenChange(!open)}
          className="flex w-full items-center justify-between gap-3 rounded-card px-4 py-2.5 text-left outline-none -outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
        >
          <span>{title}</span>
          <span className="flex items-center gap-3">
            {meta && <span className="type-meta font-normal">{meta}</span>}
            <ChevronDown aria-hidden className={cn("size-4 text-ink-secondary transition-transform motion-reduce:transition-none", open && "rotate-180")} />
          </span>
        </button>
      </h3>
      {open && (
        <div id={id} className="border-t border-border px-4 py-4">
          {children}
        </div>
      )}
    </section>
  );
}

const RUN_NOTE: Record<"live" | "demo", string> = {
  live: "Live run: calls the configured language model. Quick Reads usually finish within a minute; larger studies take longer.",
  demo: "Demo project: runs on fixtures. It is free and calls no model.",
};

/** The one primary action of a setup form, with what pressing it will do and cost. */
export function RunButton({ kind, pending, mode, blocked, error, onRetry }: { kind: RunKind; pending: boolean; mode: "live" | "demo"; blocked?: string | null; error: unknown; onRetry?: () => void }) {
  const label = kind === "quick_read" ? "Run Quick Read" : kind === "audience_study" ? "Run Audience Study" : "Run Risk Check";
  return (
    <div className="space-y-3 border-t border-border pt-4">
      {error != null && <ErrorState error={error} onRetry={onRetry} />}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" size="lg" disabled={pending || Boolean(blocked)}>
          <Play aria-hidden />
          {pending ? "Starting…" : label}
        </Button>
        <p className="max-w-[60ch] text-[12.5px] text-ink-secondary">{blocked ?? RUN_NOTE[mode]}</p>
      </div>
    </div>
  );
}
