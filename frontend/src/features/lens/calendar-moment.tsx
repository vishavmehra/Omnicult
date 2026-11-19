"use client";

import { Hourglass } from "lucide-react";

import { cn } from "@/lib/utils";

import type { LensCalendarEntry } from "./api";
import type { Kind } from "./calendar-logic";

/**
 * The three kinds of dated moment, each a colour and a shape, so the kind never rests on colour alone: a square for a
 * public holiday, a diamond for a festival, a ring for an observance. The colours are theme tokens that read on both the
 * graphite and the clay ground: ember for public holidays, the studio rose for festivals, the lab blue for observances.
 */
export const KIND_COLOR: Record<Kind, string> = {
  public_holiday: "var(--pop)",
  festival: "var(--role-studio-strong)",
  observance: "var(--role-lab-strong)",
};

export const KIND_LABEL: Record<Kind, string> = {
  public_holiday: "Public holiday",
  festival: "Festival",
  observance: "Observance",
};

/** The kind's shape. `color` overrides the kind colour (a pinned day draws its marks in the ink on ember). */
export function KindMark({ kind, color, className }: { kind: Kind; color?: string; className?: string }) {
  const c = color ?? KIND_COLOR[kind];
  return (
    <svg aria-hidden viewBox="0 0 10 10" className={cn("size-2.5 shrink-0 overflow-visible", className)}>
      {kind === "public_holiday" && <rect x="1" y="1" width="8" height="8" rx="1.8" style={{ fill: c }} />}
      {kind === "festival" && <path d="M5 0 10 5 5 10 0 5Z" style={{ fill: c }} />}
      {kind === "observance" && <circle cx="5" cy="5" r="3.6" style={{ fill: "none", stroke: c, strokeWidth: 2.4 }} />}
    </svg>
  );
}

function KindBadge({ kind }: { kind: Kind }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2 py-0.5 text-[11.5px] font-medium text-ink-secondary">
      <KindMark kind={kind} />
      {KIND_LABEL[kind]}
    </span>
  );
}

const sameText = (a: string, b: string) => a.toLowerCase().includes(b.toLowerCase());

/**
 * One moment, everything known about it: its name and kind, whether the date is tentative, what it is (a Wikipedia
 * description found through the Google Knowledge Graph, with its attribution and link), why it matters for a campaign
 * (each reason computed from data by the server) and the lists or claims that give the date.
 */
export function MomentBody({ entry, level = 3 }: { entry: LensCalendarEntry; level?: 3 | 4 }) {
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Heading className="text-[14.5px] leading-snug font-semibold text-ink">{entry.name}</Heading>
        <KindBadge kind={entry.kind} />
        {entry.tentative && (
          <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-[11.5px] font-medium text-warning">
            <Hourglass aria-hidden className="size-3" />
            Tentative date
          </span>
        )}
      </div>
      {entry.about && (
        <p className="text-[13px] leading-relaxed text-ink-body">
          {entry.about.text}{" "}
          {entry.about.url ? (
            <a href={entry.about.url} target="_blank" rel="noreferrer" className="text-[11.5px] text-rose underline-offset-2 hover:underline">
              {entry.about.attribution}
            </a>
          ) : (
            <span className="text-[11.5px] text-ink-muted">{entry.about.attribution}</span>
          )}
        </p>
      )}
      {entry.why.length > 0 && (
        <div>
          <p className="type-meta">Why it matters</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[12.5px] leading-snug text-ink-body marker:text-ink-muted">
            {entry.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {entry.sources.length > 0 && (
        <p className="type-meta">
          Dated by{" "}
          {entry.sources.map((s, i) => (
            <span key={`${s.label}-${i}`}>
              {i > 0 && "; "}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" className="text-rose underline-offset-2 hover:underline">
                  {s.label}
                </a>
              ) : (
                <span className="text-ink-secondary">{s.label}</span>
              )}
              {s.publisher && !sameText(s.label, s.publisher) ? ` (${s.publisher})` : ""}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
