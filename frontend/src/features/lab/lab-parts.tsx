"use client";

import { Ban, Check, ChevronDown, CircleAlert, CircleCheck, LoaderCircle, MessageSquareText, TriangleAlert, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { KindTag } from "@/components/evidence/evidence-row";
import { Tag } from "@/components/evidence/badges";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { useNow } from "@/hooks/use-now";
import { formatDateTime, formatElapsed, formatRelative, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { citedClaims, isGrounded, REACTIONS } from "./labels";
import type { GroundingClaim, PointCount, QuickReadResult, ReactionDistribution, RunMetadata, RunSummary } from "./types";
import { isActive } from "./types";

// ---------- layout ----------

/** A titled clay panel. Content inside stays flat: ledger rows, text, tables. */
export function Panel({ id, title, meta, children, className }: { id?: string; title: ReactNode; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={cn("rounded-card border border-border bg-surface", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-2.5">
        <h3 id={id} className="text-[14px] font-semibold text-ink">
          {title}
        </h3>
        {meta && <span className="type-meta">{meta}</span>}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

/** Native disclosure: keyboard and screen-reader behaviour for free. */
export function Disclosure({ summary, children, className, defaultOpen }: { summary: ReactNode; children: ReactNode; className?: string; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className={cn("group/disc", className)}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-sm text-[12.5px] font-medium text-ink-secondary hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronDown aria-hidden className="size-3.5 transition-transform group-open/disc:rotate-180 motion-reduce:transition-none" />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

// ---------- form controls ----------

export const CONTROL =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-surface-raised px-2.5 text-[14px] text-ink shadow-well outline-none transition-colors focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-surface-muted";

export function NativeSelect({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select {...props} className={cn(CONTROL, "pr-7", className)}>
      {children}
    </select>
  );
}

/** A group of toggle chips (checkbox semantics). Each chip shows a check when on, so state never rests on colour. */
export function ChipSelect<T extends string>({
  legend,
  hint,
  options,
  value,
  onChange,
  disabled,
}: {
  legend: string;
  hint?: ReactNode;
  options: { value: T; label: string }[];
  value: T[];
  onChange(next: T[]): void;
  disabled?: boolean;
}) {
  const hintId = useId();
  return (
    <fieldset className="min-w-0 space-y-1.5" aria-describedby={hint ? hintId : undefined} disabled={disabled}>
      <legend className="mb-1.5 text-[13px] font-medium text-ink">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = value.includes(o.value);
          return (
            <label key={o.value} className="relative">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={on}
                onChange={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
              />
              <span
                className={cn(
                  "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 text-[13px] transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
                  on ? "border-ink-secondary bg-surface-raised font-medium text-ink shadow-clay" : "border-border-strong/55 text-ink-secondary hover:bg-surface-muted",
                )}
              >
                {on && <Check aria-hidden className="size-3.5" />}
                {o.label}
              </span>
            </label>
          );
        })}
      </div>
      {hint && (
        <p id={hintId} className="max-w-prose text-xs text-ink-secondary">
          {hint}
        </p>
      )}
    </fieldset>
  );
}

/** A short list picked from a long set: choose from a menu, remove with the chip's button. */
export function ListPicker({
  id,
  label,
  options,
  value,
  onChange,
  max,
  hint,
  required,
  placeholder,
}: {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange(next: string[]): void;
  max: number;
  hint?: ReactNode;
  required?: boolean;
  placeholder: string;
}) {
  const names = new Map(options.map((o) => [o.value, o.label]));
  const full = value.length >= max;
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink">
        {label}
        {required ? <span className="text-danger"> *</span> : <span className="font-normal text-ink-secondary"> (optional)</span>}
      </label>
      <NativeSelect
        id={id}
        value=""
        disabled={full}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => e.target.value && onChange([...value, e.target.value])}
      >
        <option value="">{full ? `Limit of ${max} reached` : placeholder}</option>
        {options
          .filter((o) => !value.includes(o.value))
          .map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
      </NativeSelect>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Selected: ${label}`}>
          {value.map((v) => (
            <li key={v} className="inline-flex h-7 items-center gap-1 rounded-lg border border-border-strong/55 bg-surface-raised pr-1 pl-2.5 text-[13px] text-ink">
              {names.get(v) ?? v}
              <button
                type="button"
                aria-label={`Remove ${names.get(v) ?? v}`}
                onClick={() => onChange(value.filter((x) => x !== v))}
                className="grid size-5 place-items-center rounded-sm text-ink-secondary hover:bg-surface-muted hover:text-ink"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {hint && (
        <p id={`${id}-hint`} className="max-w-prose text-xs text-ink-secondary">
          {hint}
        </p>
      )}
    </div>
  );
}

export function FieldBlock({ label, htmlFor, hint, error, optional, children, className }: { label: string; htmlFor: string; hint?: ReactNode; error?: string | null; optional?: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}
        {optional && <span className="font-normal text-ink-secondary"> (optional)</span>}
      </label>
      {children}
      {hint && (
        <p id={`${htmlFor}-hint`} className="max-w-prose text-xs text-ink-secondary">
          {hint}
        </p>
      )}
      {error && (
        <p role="alert" className="max-w-prose text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------- run state ----------

type BannerRun = Pick<QuickReadResult, "status" | "mode" | "progress" | "error" | "created_at"> & { run_metadata: Pick<RunMetadata, "started_at" | "completed_at"> };

const TONE = {
  info: "border-info/30 bg-info-soft/60",
  success: "border-success/30 bg-success-soft/50",
  warning: "border-warning/40 bg-warning-soft/70",
  danger: "border-danger/35 bg-danger-soft/60",
  neutral: "border-border bg-surface-muted/60",
} as const;

/**
 * The run's own state, as the server reports it: stage and message while it moves, the error as reported when it fails, and
 * a plain "completed with gaps" for partial results. Never a made-up percentage.
 */
export function RunBanner({ run, label, onNewRun }: { run: BannerRun; label: string; onNewRun?: () => void }) {
  const active = isActive(run.status);
  const now = useNow(active);
  const start = Date.parse(run.run_metadata.started_at ?? run.created_at);
  const end = run.run_metadata.completed_at ? Date.parse(run.run_metadata.completed_at) : now;
  const elapsed = formatElapsed(end - start);
  const err = run.error;
  const notConfigured = err?.code === "PROVIDER_NOT_CONFIGURED";

  let tone: keyof typeof TONE = "neutral";
  let Icon = Ban;
  let title = "";
  let lines: ReactNode[] = [];
  if (run.status === "queued" || run.status === "running") {
    tone = "info";
    Icon = LoaderCircle;
    title = `${label}: ${run.status === "queued" ? "queued" : "running"}`;
    lines = [
      run.progress?.message && <p key="m" className="text-ink">{run.progress.message}</p>,
      <p key="s" className="type-meta">
        {run.progress && run.progress.stage !== "completed" && <>Stage: {humanize(run.progress.stage)} · {run.progress.completed_steps} of {run.progress.total_steps} stages done · </>}
        {elapsed} elapsed. The run continues on the server if you leave this page.
      </p>,
    ];
  } else if (run.status === "completed") {
    tone = "success";
    Icon = CircleCheck;
    title = `${label}: completed`;
    lines = [<p key="s" className="type-meta">Finished {formatRelative(run.run_metadata.completed_at)} · took {elapsed}</p>];
  } else if (run.status === "partial") {
    tone = "warning";
    Icon = TriangleAlert;
    title = `${label}: completed with gaps`;
    lines = [
      <p key="m" className="text-ink">Some stages did not finish. What was saved is shown below, and the limitations name what is missing.</p>,
      err && <p key="e" className="text-ink">{err.message}</p>,
      <p key="s" className="type-meta">{err?.stage && <>Incomplete stage: {humanize(err.stage)} · </>}took {elapsed}</p>,
    ];
  } else {
    tone = "danger";
    Icon = CircleAlert;
    title = notConfigured ? "No language model provider is configured" : `${label}: ${run.status === "cancelled" ? "cancelled" : "failed"}`;
    lines = [
      <p key="m" className="text-ink">{err?.message ?? "The run stopped without an error message. No results were saved."}</p>,
      notConfigured && <p key="n" className="text-ink-secondary">A live project needs a provider configured on the server.</p>,
      <p key="s" className="type-meta">
        {err?.stage && <>Failed at: {humanize(err.stage)} · </>}
        {err && <span className="font-mono">{err.code}</span>}
        {err && <> · No results were saved, so starting a new run is safe.{!err.retryable && " The server marks this failure as not retryable unchanged: change the settings or check the provider first."}</>}
      </p>,
    ];
  }

  return (
    <div role={run.status === "failed" ? "alert" : "status"} aria-live={run.status === "failed" ? "assertive" : "polite"} className={cn("rounded-md border px-3.5 py-3", TONE[tone])}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", active && "animate-spin motion-reduce:animate-none", tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : tone === "success" ? "text-success" : tone === "info" ? "text-info" : "text-ink-secondary")} />
        <div className="min-w-0 flex-1 space-y-1 text-[13.5px]">
          <p className="font-medium text-ink">{title}</p>
          {lines}
          {run.status === "failed" && onNewRun && (
            <button type="button" onClick={onNewRun} className="mt-1 text-[12.5px] font-medium text-rose underline underline-offset-2">
              Start a new run
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- run list ----------

const KIND_NOUN: Record<RunSummary["kind"], string> = {
  quick_read: "Quick Read",
  audience_study: "Audience Study",
  risk_check: "Risk Check",
  focus_group: "Focus Group",
  buzz_sim: "Buzz Simulator",
  message_check: "Message Check",
};

/** Earlier runs of one kind as a ruled list: the open one is marked, each shows its state word, so a finished or failed run is visible at a glance. */
export function RunPicker({
  runs,
  selectedId,
  onSelect,
  regionName,
  describe,
  limit = 4,
}: {
  runs: RunSummary[];
  selectedId: string | null | undefined;
  onSelect(id: string): void;
  regionName(code: string): string;
  describe(run: RunSummary): string;
  limit?: number;
}) {
  const [all, setAll] = useState(false);
  if (runs.length === 0) return null;
  const shown = all ? runs : runs.slice(0, limit);
  return (
    <div className="space-y-1.5">
      <ul className="ledger-rules overflow-hidden rounded-card border border-border bg-surface" aria-label="Earlier runs">
        {shown.map((r) => {
          const on = r.id === selectedId;
          return (
            <li key={r.id}>
              <button
                type="button"
                aria-current={on ? "true" : undefined}
                onClick={() => onSelect(r.id)}
                className={cn(
                  "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 px-3.5 py-2 text-left outline-none -outline-offset-2 hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-ring",
                  on && "bg-surface-muted",
                )}
              >
                <span className="min-w-0">
                  <span className={cn("block truncate text-[13.5px]", on ? "font-semibold text-ink" : "text-ink-body")}>
                    {on && <Check aria-hidden className="mr-1 inline size-3.5 -translate-y-px" />}
                    {r.region_codes.map(regionName).join(", ") || KIND_NOUN[r.kind]} · {describe(r)}
                  </span>
                  <span className="type-meta" title={formatDateTime(r.created_at)}>
                    {formatRelative(r.created_at)}
                  </span>
                </span>
                <RunStatusBadge status={r.status} />
              </button>
            </li>
          );
        })}
      </ul>
      {runs.length > limit && (
        <button type="button" onClick={() => setAll((v) => !v)} className="text-[12.5px] font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
          {all ? "Show fewer runs" : `Show ${runs.length - limit} earlier ${runs.length - limit === 1 ? "run" : "runs"}`}
        </button>
      )}
    </div>
  );
}

// ---------- reaction distribution ----------

/** Reaction counts as ruled rows: a word and icon per reaction, a count out of the denominator, and a bar that only repeats the count. */
export function DistributionLedger({ dist, noun = "participants" }: { dist: ReactionDistribution; noun?: string }) {
  return (
    <div className="space-y-2">
      <ul className="ledger-rules type-ledger text-[13.5px]">
        {REACTIONS.map(({ key, label, Icon }) => {
          const n = dist.counts[key] ?? 0;
          return (
            <li key={key} className="grid grid-cols-[7.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 py-1.5 sm:grid-cols-[9rem_minmax(0,1fr)_5rem]">
              <span className={cn("inline-flex items-center gap-1.5", n === 0 ? "text-ink-muted" : "text-ink")}>
                <Icon aria-hidden className="size-3.5 shrink-0" />
                {label}
              </span>
              <span aria-hidden className="clay-well h-2.5 rounded-[4px] p-[2px]">
                <span className="block h-full rounded-[2px] bg-ink-secondary" style={{ width: dist.denominator ? `${(n / dist.denominator) * 100}%` : 0 }} />
              </span>
              <span className="text-right text-ink-body">
                {n} <span className="text-ink-muted">of {dist.denominator}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="type-meta">
        Counted from {dist.denominator} {noun} that responded.
        {dist.failed > 0 && ` ${dist.failed} did not respond and are left out of the counts, not guessed.`}
      </p>
    </div>
  );
}

// ---------- grounded and ungrounded statements ----------

function CitedClaims({ claims }: { claims: GroundingClaim[] }) {
  return (
    <ul className="mt-1.5 space-y-1.5 rounded-md bg-surface-muted/70 px-3 py-2">
      {claims.map((c) => (
        <li key={c.id} className="space-y-1">
          <p className="text-[13px] leading-snug text-ink">{c.value_text}</p>
          <p className="type-ledger flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-secondary">
            <KindTag kind={c.kind} />
            <span>{c.region_code ?? "Country-wide"}</span>
            <ConfidenceIndicator level={c.confidence} />
            <span className="font-mono text-[11px] text-ink-muted">{c.id.slice(0, 8)}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

/**
 * Statements with their basis. "Claim-supported" is shown only when the statement cites an observed or calculated claim
 * the run was actually given; every other statement is labelled a model interpretation, however confident it sounds.
 */
export function StatementList({ points, claims, denominator, empty }: { points: PointCount[]; claims: GroundingClaim[]; denominator: number; empty: string }) {
  if (points.length === 0) return <p className="text-[13px] text-ink-muted">{empty}</p>;
  return (
    <ul className="ledger-rules">
      {points.map((p, i) => {
        const grounded = isGrounded(p, claims);
        const cites = citedClaims(p, claims);
        return (
          <li key={`${i}-${p.text}`} className="space-y-1 py-2">
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
              <p className="min-w-0 flex-1 text-[14px] leading-snug text-ink">{p.text}</p>
              <p className="type-ledger shrink-0 text-[12.5px] text-ink-secondary">
                {p.participants} of {denominator}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {grounded ? (
                <Tag className="border-border-strong/60 bg-surface-raised text-ink" title="Cites at least one observed or calculated claim stored for the region.">
                  <Check aria-hidden />
                  Claim-supported
                </Tag>
              ) : (
                <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="No observed or calculated claim is cited. A model's reading, not evidence.">
                  <MessageSquareText aria-hidden />
                  Interpretation: no claim cited
                </Tag>
              )}
            </div>
            {grounded && <Disclosure summary={`Cites ${cites.length} ${cites.length === 1 ? "claim" : "claims"}`}><CitedClaims claims={cites} /></Disclosure>}
          </li>
        );
      })}
    </ul>
  );
}
