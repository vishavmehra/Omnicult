"use client";

import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { cn } from "@/lib/utils";

import type { GenerateKind, Run } from "./api";

export const usd = (value: number | null | undefined) => (value == null ? "not priced" : `$${value < 0.01 ? value.toFixed(4) : value.toFixed(3)}`);

export function mmss(ms: number) {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function seconds(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Model output is tagged once per view, in the same quiet style as the evidence labels. */
export function AiTag({ children = "AI proposal" }: { children?: ReactNode }) {
  return <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">{children}</Tag>;
}

/** The one quiet source line of a view. */
export function SourceLine({ children }: { children: ReactNode }) {
  return <p className="type-meta">{children}</p>;
}

/** A plain notice for a condition the person can read and act on. */
export function Notice({ tone = "warning", children }: { tone?: "warning" | "info"; children: ReactNode }) {
  return (
    <p
      role="note"
      className={cn("rounded-lg border px-3.5 py-2.5 text-[13.5px] text-ink", tone === "warning" ? "border-warning/40 bg-warning-soft" : "border-info/30 bg-info-soft")}
    >
      {children}
    </p>
  );
}

/** Native select with the design system's field styling. */
export const SELECT =
  "h-9 w-full min-w-0 rounded-lg border border-input bg-surface px-2.5 text-sm text-ink shadow-card outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50 max-sm:h-11";
export const INPUT =
  "h-9 w-full min-w-0 rounded-lg border border-input bg-surface px-2.5 text-[14px] text-ink shadow-card outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 max-sm:h-11";
export const TEXTAREA =
  "w-full min-w-0 resize-y rounded-lg border border-input bg-surface px-2.5 py-2 text-[14px] leading-relaxed text-ink shadow-card outline-none placeholder:text-ink-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25";

/** A pressable chip: a prompt idea, a format, a voice. `pressed` is announced; the whole chip is the 44px-friendly target on phones. */
export function Chip({
  pressed,
  onClick,
  children,
  className,
  title,
  disabled,
}: {
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
  title?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={pressed}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-[13px] outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/30 disabled:opacity-50 max-sm:min-h-11",
        pressed ? "border-primary bg-pop-soft text-ink shadow-clay-pressed" : "border-border-strong/45 bg-surface-raised text-ink-body shadow-card hover:bg-surface-muted",
        className,
      )}
    >
      {children}
    </button>
  );
}

const STAGES: Record<GenerateKind, string[]> = {
  image: ["Reading the brief and Brand Kit", "Generating the scene", "Placing logo, product and headline in code", "Checking the finished image"],
  voice: ["Loading the lines", "Speaking each line", "Joining the lines into one track", "Checking the timings"],
  jingle: ["Reading the hints", "Composing the jingle", "Cutting the clip to length", "Checking the clip"],
};

/** The four stages of a run, with the one that is working. Nothing here is a time estimate or a percentage. */
export function RunLadder({ kind, run }: { kind: GenerateKind; run: Run | undefined }) {
  const current = run?.progress?.completed_steps ?? 0;
  const done = run?.status === "completed" || run?.status === "partial";
  return (
    <ol className="space-y-2" aria-label="Stages of this run">
      {STAGES[kind].map((label, index) => {
        const state = done || index < current ? "done" : index === current ? "working" : "waiting";
        return (
          <li key={label} className={cn("flex items-center gap-2.5 text-[13.5px]", state === "waiting" ? "text-ink-muted" : "text-ink")}>
            {state === "done" ? (
              <CircleCheck aria-hidden className="size-4 text-success" />
            ) : state === "working" ? (
              <LoaderCircle aria-hidden className="size-4 animate-spin text-primary" />
            ) : (
              <span aria-hidden className="size-4 rounded-full border border-border-strong/60" />
            )}
            <span className={state === "working" ? "gen-pulse" : undefined}>{label}</span>
            <span className="sr-only">{state === "done" ? "done" : state === "working" ? "working now" : "waiting"}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** The reason a run failed, kept exactly as the server reported it. The generator stays available below. */
export function RunError({ error, onRetry }: { error: { code: string; message: string; retryable: boolean } | null | undefined; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger-soft px-3.5 py-3 text-[13.5px] text-ink">
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">This run did not finish.</p>
        <p className="text-ink-body">{error?.message ?? "No file was saved."}</p>
        {error && <p className="type-meta">{error.code}</p>}
        {onRetry && error?.retryable !== false && (
          <button type="button" onClick={onRetry} className="text-[13px] font-medium text-primary underline underline-offset-2">
            Run it again
          </button>
        )}
      </div>
    </div>
  );
}

/** A brand colour: click copies the hex. */
export function Swatch({ hex, name }: { hex: string; name: string }) {
  return (
    <button
      type="button"
      title={`${name} ${hex}. Click to copy.`}
      aria-label={`${name}, ${hex}. Copy the colour code.`}
      onClick={() => void navigator.clipboard?.writeText(hex)}
      className="size-6 rounded-full border border-border-strong/50 shadow-card outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
      style={{ background: hex }}
    />
  );
}

/** A tiny rectangle with the proportions of an image format. */
export function FormatGlyph({ width, height }: { width: number; height: number }) {
  const scale = 18 / Math.max(width, height);
  return <span aria-hidden className="inline-block rounded-[3px] border border-current" style={{ width: Math.round(width * scale), height: Math.round(height * scale) }} />;
}
