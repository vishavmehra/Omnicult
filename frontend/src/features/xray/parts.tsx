"use client";

import { Bot, Eye, FileText, Mic, MessageSquareText, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { cn } from "@/lib/utils";

import type { Provenance } from "./api";

/** 4710 -> "0:04.7". Scene times are shown to a tenth of a second. */
export function clock(ms: number | null | undefined) {
  if (ms == null) return "n/a";
  const total = Math.max(0, ms) / 1000;
  const m = Math.floor(total / 60);
  return `${m}:${(total - m * 60).toFixed(1).padStart(4, "0")}`;
}

export function span(start: number, end: number | null) {
  return end == null ? clock(start) : `${clock(start)} to ${clock(end)}`;
}

type Label = { text: string; Icon: LucideIcon; className: string; title: string };

const SOLID = "border-border bg-surface-muted text-ink";
const DASHED = "border-dashed border-ink-secondary/50 bg-surface text-ink-secondary";

const LABELS: Record<Provenance, Label> = {
  observed: {
    text: "Read from frame",
    Icon: Eye,
    className: SOLID,
    title: "A vision model read this from the keyframe. Code kept it only because it appears in that frame's observations.",
  },
  transcribed: { text: "Transcribed", Icon: Mic, className: SOLID, title: "Machine transcription of the audio." },
  user_provided: { text: "Your sidecar", Icon: FileText, className: SOLID, title: "From the SRT, WebVTT or notes file you uploaded with the creative." },
  model_generated: {
    text: "Model observation",
    Icon: Bot,
    className: DASHED,
    title: "Reported by a model from the frames and transcript. Cited ids were checked in code; the reading itself was not.",
  },
  interpretation: {
    text: "Model interpretation",
    Icon: MessageSquareText,
    className: DASHED,
    title: "A model's cultural reading. Not an observed fact.",
  },
};

/** Says what kind of thing a scene field is. The kind comes from the backend (set by code), never from a model. */
export function ProvenanceTag({ kind, className }: { kind: Provenance; className?: string }) {
  const { text, Icon, className: tone, title } = LABELS[kind];
  return (
    <Tag className={cn(tone, className)} title={title}>
      <Icon aria-hidden />
      {text}
    </Tag>
  );
}

/** A titled block inside a ruled clay panel: a sentence-case heading, optional tag and meta, then the content. */
export function Block({ title, tag, meta, children }: { title: string; tag?: ReactNode; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <h3 className="text-[13.5px] font-semibold text-ink">{title}</h3>
        {tag}
        {meta && <span className="type-meta ml-auto">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

/** Short model-reported phrases as ruled chips. */
export function Phrases({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <li key={i} className="rounded-sm border border-border bg-surface-muted px-2 py-0.5 text-[12.5px] text-ink-body">
          {item}
        </li>
      ))}
    </ul>
  );
}

/** Ids of the frames (f1) and transcript segments (t1) a statement rests on. */
export function EvidenceIds({ ids, titles }: { ids: string[]; titles?: Record<string, string> }) {
  if (!ids.length) return <span className="type-meta">Cites nothing</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1 align-middle">
      <span className="type-meta">Rests on</span>
      {ids.map((id) => (
        <code key={id} title={titles?.[id]} className="rounded-sm border border-border bg-surface px-1.5 py-px font-mono text-[11.5px] text-ink-secondary">
          {id}
        </code>
      ))}
    </span>
  );
}
