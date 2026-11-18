"use client";

import { CircleAlert, Info, ShieldAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type Tone = "high" | "medium" | "low" | "problem" | "review" | "info" | "ok";

const TONES: Record<Tone, { Icon: LucideIcon; text: string; word: string }> = {
  high: { Icon: ShieldAlert, text: "text-danger", word: "High" },
  medium: { Icon: TriangleAlert, text: "text-warning", word: "Medium" },
  low: { Icon: Info, text: "text-ink-secondary", word: "Low" },
  problem: { Icon: ShieldAlert, text: "text-danger", word: "Problem" },
  review: { Icon: TriangleAlert, text: "text-warning", word: "Review" },
  info: { Icon: Info, text: "text-ink-secondary", word: "Info" },
  ok: { Icon: CircleAlert, text: "text-success", word: "OK" },
};

/** A level as icon, word and colour together (the Word-and-Icon rule). `label` overrides the word ("High severity"). */
export function ToneTag({ tone, label, className }: { tone: Tone; label?: string; className?: string }) {
  const { Icon, text, word } = TONES[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium whitespace-nowrap", text, className)}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {label ?? word}
    </span>
  );
}

export type Mark = { start: number; end: number; tone: "problem" | "review" | "info" | "claim" };

const MARK_CLASS: Record<Mark["tone"], string> = {
  problem: "bg-danger/15 underline decoration-danger decoration-wavy underline-offset-4",
  review: "bg-warning/20 underline decoration-warning decoration-wavy underline-offset-4",
  info: "bg-surface-muted underline decoration-ink-muted decoration-dotted underline-offset-4",
  claim: "bg-warning/25 outline outline-1 outline-warning/60",
};

/**
 * The element's own text with the spans the checks point at marked (word and shape, not colour alone: wavy for problems,
 * dotted for information). Spans outside the text, empty or overlapping an earlier one are ignored.
 */
export function MarkedText({ text, marks, lang, className }: { text: string; marks: Mark[]; lang?: string | null; className?: string }) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const m of [...marks].sort((a, b) => a.start - b.start || b.end - a.end)) {
    if (m.start < at || m.end <= m.start || m.end > text.length) continue;
    if (m.start > at) parts.push(text.slice(at, m.start));
    parts.push(
      <mark key={`${m.start}-${m.end}`} className={cn("rounded-[3px] px-0.5 text-ink", MARK_CLASS[m.tone])}>
        {text.slice(m.start, m.end)}
      </mark>,
    );
    at = m.end;
  }
  parts.push(text.slice(at));
  return (
    <p lang={lang ?? undefined} className={cn("text-[15px] leading-relaxed whitespace-pre-line text-ink", className)}>
      {parts}
    </p>
  );
}

/** Where in the creative something is: the scene's time span and the box, as quiet mono text. */
export function AnchorLine({ anchor, elementId }: { anchor: { scene_id?: string | null; start_ms?: number | null; end_ms?: number | null; bbox?: number[] | null }; elementId: string }) {
  const clock = (ms: number) => `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(1).padStart(4, "0")}`;
  const parts = [
    anchor.start_ms != null ? (anchor.end_ms != null ? `${clock(anchor.start_ms)} to ${clock(anchor.end_ms)}` : clock(anchor.start_ms)) : null,
    anchor.bbox ? `box ${anchor.bbox.map((n) => Math.round(n * 100)).join(", ")}%` : null,
  ].filter(Boolean);
  return (
    <p className="font-mono text-[11.5px] text-ink-muted">
      {elementId}
      {parts.length > 0 && <> · {parts.join(" · ")}</>}
    </p>
  );
}

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
