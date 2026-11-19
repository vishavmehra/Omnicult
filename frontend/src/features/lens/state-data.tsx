"use client";

import { CalendarDays, Hammer, Languages, LoaderCircle, Search, TrendingUp, TriangleAlert, CircleCheck, Clock3 } from "lucide-react";

import { cn } from "@/lib/utils";

import type { LensAutoBuild, LensFigure, LensStateData } from "./api";
import { dayLabel } from "./format";
import { formatFact, versusIndia, type FactUnit } from "./state-facts-logic";

/**
 * State data: what public datasets say about a state, shown as data beside the evidence (never counted in the Evidence
 * Meter). Every number is the API's own; these components only format, order and draw it.
 */

export const nfIN = new Intl.NumberFormat("en-IN");
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

export function figureOf(data: LensStateData, key: string): LensFigure | undefined {
  return data.figures.find((f) => f.key === key);
}

/** A short form for a map tile: 79%, 94.6, ₹2.8L, 306.8M. */
export function shortFigure(unit: FactUnit | "count", value: number): string {
  if (unit === "percent") return `${Math.round(value)}%`;
  if (unit === "inr") return `₹${compact.format(value)}`;
  if (unit === "million") return `${compact.format(value)}M`;
  if (unit === "count") return nfIN.format(value);
  return compact.format(value);
}

/** The figures a state card leads with, in this order, where the state has them. */
const HEADLINE = ["internet_per100", "home_no_internet", "nsdp", "literacy", "women_bank", "tourist_visits_domestic"];

function Figure({ fig }: { fig: LensFigure }) {
  const unit = fig.unit as FactUnit;
  const versus = versusIndia(unit, fig.value, fig.national);
  return (
    <div className="min-w-0 space-y-0.5 rounded-lg border border-border/70 bg-surface-raised/60 px-3 py-2">
      <p className="text-[12px] leading-snug text-ink-secondary">{fig.label}</p>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="type-ledger text-[18px] font-semibold text-ink">{formatFact(unit, fig.value)}</span>
        <span className="rounded-full bg-surface-muted px-1.5 text-[10.5px] tabular-nums text-ink-secondary">{fig.period}</span>
      </p>
      {versus && <p className={cn("text-[11.5px]", versus.direction === "above" ? "text-success" : versus.direction === "below" ? "text-ink-secondary" : "text-ink-muted")}>{versus.text}</p>}
    </div>
  );
}

/** The state at a glance: headline figures, mother tongues, this week's searches and the next public holidays. */
export function StateDataCard({
  data,
  name,
  onOpenCalendar,
  figures = true,
  className,
}: {
  data: LensStateData;
  name: string;
  onOpenCalendar?: () => void;
  figures?: boolean;
  className?: string;
}) {
  const headline = figures ? HEADLINE.map((k) => figureOf(data, k)).filter((f): f is LensFigure => Boolean(f)).slice(0, 4) : [];
  const census = data.languages.some((l) => l.share !== null);
  return (
    <div className={cn("space-y-4", className)}>
      {headline.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {headline.map((f) => (
            <Figure key={f.key} fig={f} />
          ))}
        </div>
      )}
      {data.languages.length > 0 && (
        <div className="space-y-1.5">
          <p className="type-meta flex items-center gap-1.5">
            <Languages aria-hidden className="size-3.5" />
            {census ? "Mother tongues, census 2011" : "Official languages"}
          </p>
          <ul className="space-y-1">
            {data.languages.slice(0, 3).map((l) => (
              <li key={`${l.code}-${l.name}`} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] items-center gap-2 text-[13px]">
                <span className="truncate text-ink">{l.name}</span>
                {l.share !== null ? (
                  <span className="clay-well h-2 overflow-hidden rounded-full p-px" role="img" aria-label={`${l.name}: ${l.share}% in 2011`}>
                    <span className="block h-full rounded-full bg-[var(--role-lens-strong)]" style={{ width: `${Math.max(l.share, 1)}%` }} />
                  </span>
                ) : (
                  <span className="text-[12px] text-ink-muted">{l.role === "primary" ? "principal" : "additional"}</span>
                )}
                <span className="type-ledger text-[12.5px] text-ink-secondary">{l.share !== null ? `${l.share}%` : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(data.searches.length > 0 || data.rising.length > 0) && (
        <div className="space-y-1.5">
          <p className="type-meta flex items-center gap-1.5">
            <Search aria-hidden className="size-3.5" />
            This week&apos;s top searches where {name} scores highest
            {data.search_week ? `, week of ${dayLabel(data.search_week)}` : ""}
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {data.searches.map((t) => (
              <li key={`top-${t.term}`} className="rounded-full border border-border bg-surface-raised px-2.5 py-0.5 text-[12.5px] text-ink" title={`Score ${t.score} of 100`}>
                {t.term} <span className="type-ledger text-ink-muted">{t.score}</span>
              </li>
            ))}
            {data.rising.slice(0, 2).map((t) => (
              <li key={`rise-${t.term}`} className="inline-flex items-center gap-1 rounded-full bg-pop-soft px-2.5 py-0.5 text-[12.5px] text-ink" title={`Rising, score ${t.score} of 100`}>
                <TrendingUp aria-label="Rising" className="size-3 text-pop" />
                {t.term}
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.holidays > 0 && (
        <div className="space-y-1.5">
          <p className="type-meta flex items-center gap-1.5">
            <CalendarDays aria-hidden className="size-3.5" />
            {data.holidays} public holidays on the {data.holidays_year} list
          </p>
          {data.next_holidays.length > 0 && (
            <ul className="space-y-0.5 text-[13px]">
              {data.next_holidays.map((h) => (
                <li key={`${h.date}-${h.name}`} className="flex gap-2">
                  <span className="type-ledger w-[5.5rem] shrink-0 text-ink-secondary">{dayLabel(h.date)}</span>
                  <span className="min-w-0 text-ink">{h.name}</span>
                </li>
              ))}
            </ul>
          )}
          {onOpenCalendar && (
            <button type="button" onClick={onOpenCalendar} className="text-[12.5px] font-medium text-rose underline-offset-2 hover:underline">
              Open the moment calendar
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const STATE_COPY: Record<LensAutoBuild["regions"][number]["state"], { label: string; Icon: typeof Hammer; className: string }> = {
  queued: { label: "Queued", Icon: Clock3, className: "text-ink-secondary" },
  building: { label: "Building", Icon: LoaderCircle, className: "text-ink" },
  built: { label: "Built", Icon: CircleCheck, className: "text-success" },
  failed: { label: "Not built", Icon: TriangleAlert, className: "text-warning" },
  waiting: { label: "Not built yet", Icon: Hammer, className: "text-ink-muted" },
};

/**
 * The campaign's states while they are built in the background: "Building Kerala…" with each state's place in the queue.
 * Shown while anything is queued or building, and when a build failed (with its reason); quiet once every state is built.
 */
export function AutoBuildStrip({ status }: { status: LensAutoBuild | undefined }) {
  if (!status || status.regions.length === 0) return null;
  const building = status.regions.find((r) => r.state === "building");
  const failed = status.regions.filter((r) => r.state === "failed");
  if (!status.running && failed.length === 0) return null;
  const queued = status.regions.filter((r) => r.state === "queued").length;
  return (
    <section aria-label="Building the campaign's states" className="clay space-y-2 rounded-card border border-border bg-surface px-4 py-3">
      <p role="status" aria-live="polite" className="flex flex-wrap items-center gap-2 text-[14px] font-medium text-ink">
        {status.running ? <LoaderCircle aria-hidden className="size-4 animate-spin text-pop motion-reduce:animate-none" /> : <TriangleAlert aria-hidden className="size-4 text-warning" />}
        {building ? `Building ${building.region_name}…` : status.running ? "Waiting to build the next state…" : "Some of the campaign's states could not be built."}
        {queued > 0 && <span className="type-meta font-normal">{queued} more queued, one at a time</span>}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {status.regions.map((r) => {
          const { label, Icon, className } = STATE_COPY[r.state];
          return (
            <li key={r.region_code} className="inline-flex items-center gap-1.5 text-[12.5px]" title={r.message ?? undefined}>
              <Icon aria-hidden className={cn("size-3.5", className, r.state === "building" && "animate-spin motion-reduce:animate-none")} />
              <span className="text-ink">{r.region_name}</span>
              <span className="text-ink-muted">
                {r.role === "origin" ? "origin" : "target"} · {label}
              </span>
            </li>
          );
        })}
      </ul>
      {failed.map((r) => r.message && (
        <p key={r.region_code} className="text-[12.5px] text-ink-secondary">
          {r.region_name}: {r.message}
        </p>
      ))}
    </section>
  );
}
