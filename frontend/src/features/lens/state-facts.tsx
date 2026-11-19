"use client";

import { useEffect, useState, type ReactNode } from "react";

import { CountUp, RingGauge, Sparkline, Stagger } from "@/components/creative";
import { Button } from "@/components/ui/button";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import { useStateFacts, type StateFact } from "./api";
import { barPosition, barScale, factShape, formatFact, versusIndia, type FactUnit } from "./state-facts-logic";

/**
 * State facts: a state's published statistics as small interactive cards. Each card draws its figure by what it holds (a ring for
 * a share, a trend line for a series, bars for rural and urban), puts the all-India figure beside it where there is one, and
 * answers hover and keyboard focus with the exact figure and its period. The period is a chip on each card because it is data.
 */

function YearChip({ children }: { children: ReactNode }) {
  return <span className="shrink-0 rounded-full bg-surface-muted px-2 py-0.5 text-[11px] tabular-nums text-ink-secondary">{children}</span>;
}

/** A horizontal bar for `value` with a tick where the all-India figure falls. It grows from empty when it first paints. */
function Bar({ value, national, scale, label }: { value: number; national: number | null | undefined; scale: number; label: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setOn(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return (
    <div role="img" aria-label={label} className="relative h-2 rounded-full bg-surface-muted">
      <div className="h-full rounded-full bg-pop transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${on ? barPosition(value, scale) : 0}%` }} />
      {national !== null && national !== undefined && (
        <span aria-hidden className="absolute -top-1 h-4 w-0.5 -translate-x-1/2 rounded bg-ink" style={{ left: `${barPosition(national, scale)}%` }} />
      )}
    </div>
  );
}

function Parts({ fact, scale }: { fact: StateFact; scale: number }) {
  return (
    <ul className="space-y-2">
      {fact.parts.map((p) => (
        <li key={p.label} className="space-y-1">
          <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
            <span className="text-ink-secondary">{p.label}</span>
            <span className="type-ledger font-semibold text-ink">
              <CountUp value={p.value} format={(n) => formatFact(fact.unit as FactUnit, fact.unit === "inr" ? Math.round(n) : n)} />
            </span>
          </div>
          <Bar value={p.value} national={p.national} scale={scale} label={`${p.label}: ${formatFact(fact.unit as FactUnit, p.value)}${p.national != null ? `, India ${formatFact(fact.unit as FactUnit, p.national)}` : ""}`} />
        </li>
      ))}
    </ul>
  );
}

function FactBody({ fact }: { fact: StateFact }) {
  const unit = fact.unit as FactUnit;
  const shape = factShape({ unit, value: fact.value, series: fact.series, parts: fact.parts });
  const value = fact.value;
  const partsScale = barScale(unit, ...fact.parts.flatMap((p) => [p.value, p.national]), fact.value, fact.national);
  const grow = (n: number) => formatFact(unit, unit === "inr" ? Math.round(n) : n);
  if (shape === "parts") return <Parts fact={fact} scale={partsScale} />;
  if (value === null) return null;
  if (shape === "ring") {
    return (
      <div className="flex items-center gap-4">
        <RingGauge value={Math.round(value)} max={100} label={fact.label} size={84} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <Bar value={value} national={fact.national} scale={100} label={`${fact.label}: ${formatFact(unit, value)}`} />
        </div>
      </div>
    );
  }
  if (shape === "trend") {
    return (
      <div className="space-y-2">
        <p className="type-title text-[26px] leading-none text-ink">
          <CountUp value={value} format={grow} />
        </p>
        <Sparkline
          values={fact.series.map((p) => p.value)}
          labels={fact.series.map((p) => p.period)}
          format={(v) => formatFact(unit, v)}
          ariaLabel={`${fact.label} by period`}
          variant="area"
          height={44}
        />
      </div>
    );
  }
  const scale = barScale(unit, value, fact.national);
  return (
    <div className="space-y-2.5">
      <p className="type-title text-[26px] leading-none text-ink">
        <CountUp value={value} format={grow} />
      </p>
      <Bar value={value} national={fact.national} scale={scale} label={`${fact.label}: ${formatFact(unit, value)}`} />
      {fact.parts.length > 0 && <Parts fact={fact} scale={partsScale} />}
    </div>
  );
}

function FactCard({ fact, regionName }: { fact: StateFact; regionName: string }) {
  const [hover, setHover] = useState(false);
  const unit = fact.unit as FactUnit;
  const versus = fact.value !== null ? versusIndia(unit, fact.value, fact.national) : null;
  const exact =
    fact.value !== null
      ? `${regionName} ${formatFact(unit, fact.value)} · ${fact.period}${fact.national != null ? ` · India ${formatFact(unit, fact.national)}` : ""}`
      : fact.parts.map((p) => `${p.label} ${formatFact(unit, p.value)}`).join(" · ") + ` · ${fact.period}`;
  return (
    <li className="min-w-0">
      <div
        tabIndex={0}
        role="group"
        aria-label={`${fact.label}. ${exact}`}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
        className={cn(
          "flex h-full flex-col gap-3 rounded-card border border-border bg-surface px-4 py-4 shadow-clay outline-offset-2 transition-transform duration-200 motion-reduce:transition-none",
          "hover:-translate-y-0.5 focus-visible:-translate-y-0.5",
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-[13px] leading-snug font-semibold text-ink">{fact.label}</p>
          <YearChip>{fact.period}</YearChip>
        </div>
        <FactBody fact={fact} />
        <p aria-hidden className={cn("type-ledger mt-auto min-h-[1.25rem] text-[12px]", hover ? "text-ink" : "text-ink-secondary")}>
          {hover ? exact : (versus?.text ?? "")}
        </p>
      </div>
    </li>
  );
}

export function StateFactsPanel({ campaignId, region, regionName }: { campaignId: string; region: string; regionName: string }) {
  const query = useStateFacts(campaignId, region);
  if (query.isPending) {
    return (
      <section aria-labelledby="state-facts" aria-busy className="space-y-3">
        <SectionTitle id="state-facts">State facts</SectionTitle>
        <div role="status" className="h-28 animate-pulse rounded-card bg-surface-muted/60 motion-reduce:animate-none">
          <span className="sr-only">Loading state facts</span>
        </div>
      </section>
    );
  }
  if (query.isError) {
    return (
      <section aria-labelledby="state-facts" className="space-y-3">
        <SectionTitle id="state-facts">State facts</SectionTitle>
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">
          State facts could not be loaded.
          <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
      </section>
    );
  }
  if (query.data.groups.length === 0) return null;
  return (
    <section aria-labelledby="state-facts" className="space-y-5">
      <SectionTitle id="state-facts">State facts</SectionTitle>
      {query.data.groups.map((group) => (
        <div key={group.key} className="space-y-2.5">
          <h3 className="type-meta uppercase tracking-wide">{group.title}</h3>
          <Stagger as="ul" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {group.facts.map((fact) => (
              <FactCard key={fact.key} fact={fact} regionName={regionName} />
            ))}
          </Stagger>
        </div>
      ))}
    </section>
  );
}
