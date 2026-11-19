"use client";

import { CircleAlert, LoaderCircle, Lock } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import type { components } from "@/lib/api/schema";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

type Run = components["schemas"]["Run"];

/** Model output is tagged once per view, in the same quiet style as the evidence labels. */
export function AiTag({ children = "AI proposal" }: { children?: ReactNode }) {
  return <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">{children}</Tag>;
}

export const usd = (value: number | null | undefined) => (value == null ? "not priced" : `$${value < 0.01 ? value.toFixed(4) : value.toFixed(3)}`);

export function mmss(ms: number) {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** An asset image fetched with the API token, contained (never cropped) so a comparison shows the whole frame. */
export function AuthImage({ url, alt, className, children }: { url: string; alt: string; className?: string; children?: ReactNode }) {
  const id = url.split("/assets/")[1]?.split("/")[0] ?? url;
  const src = useAssetObjectUrl({ id, content_url: url });
  return (
    <div className={cn("relative overflow-hidden rounded-lg border border-border bg-surface-muted", className)}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated object URL, not optimizable
        <img src={src} alt={alt} className="block h-auto w-full" />
      ) : (
        <div className="grid aspect-[4/5] w-full place-items-center text-ink-muted" role="img" aria-label={`${alt} (loading)`}>
          <LoaderCircle aria-hidden className="size-5 animate-spin" />
        </div>
      )}
      {children}
    </div>
  );
}

/** Progress of a starting or running remake, and the reason when it failed. Nothing is shown once it has produced a result. */
export function RunProgress({ run, onRetry }: { run: Run | undefined; onRetry?: () => void }) {
  if (!run) return <p className="type-meta">Starting…</p>;
  if (run.status === "queued" || run.status === "running") {
    return (
      <p role="status" className="flex items-center gap-2 text-[13.5px] text-ink-body">
        <LoaderCircle aria-hidden className="size-4 animate-spin text-primary" />
        {run.progress?.message ?? "Working…"}{" "}
        <span className="type-meta">
          {run.progress ? `${humanize(run.progress.stage)} · ${run.progress.completed_steps} of ${run.progress.total_steps}` : null}
        </span>
      </p>
    );
  }
  if (run.status === "failed" || run.status === "cancelled") {
    return (
      <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger-soft px-3.5 py-3 text-[13.5px] text-ink">
        <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">{run.status === "cancelled" ? "The run was cancelled." : "The remake did not finish."}</p>
          <p className="text-ink-body">{run.error?.message ?? "No version was created."}</p>
          {run.error && <p className="type-meta">{run.error.code}</p>}
          {onRetry && run.error?.retryable !== false && (
            <button type="button" onClick={onRetry} className="text-[13px] font-medium text-primary underline underline-offset-2">
              Try again
            </button>
          )}
        </div>
      </div>
    );
  }
  return null;
}

/** The setup footer: the estimate, the confirmation a paid call needs, and the action. Demo projects call no provider. */
export function CostConfirm({
  demo,
  estimate,
  what,
  checked,
  onChange,
}: {
  demo: boolean;
  estimate: number | null | undefined;
  what: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  if (demo) return null;
  return (
    <label className="flex items-start gap-2.5 text-[13.5px] text-ink-body">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 shrink-0 accent-primary"
      />
      <span>
        Run {what}. Estimated {usd(estimate)}, charged to the project; the call is made once and never retried by the app.
      </span>
    </label>
  );
}

/** A plain notice for a capability that is missing or a result that cannot be shown. */
export function Notice({ tone = "warning", children }: { tone?: "warning" | "info"; children: ReactNode }) {
  return (
    <p
      role="note"
      className={cn(
        "rounded-lg border px-3.5 py-2.5 text-[13.5px] text-ink",
        tone === "warning" ? "border-warning/40 bg-warning-soft" : "border-info/30 bg-info-soft",
      )}
    >
      {children}
    </p>
  );
}

export function LockChip({ children }: { children: ReactNode }) {
  return (
    <Tag className="border-border bg-surface-muted text-ink-secondary">
      <Lock aria-hidden />
      {children}
    </Tag>
  );
}

/** Native select with the design system's field styling. */
export const SELECT =
  "h-9 w-full min-w-0 rounded-lg border border-input bg-surface px-2.5 text-sm text-ink shadow-card outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50";
