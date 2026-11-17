"use client";

import { Ban, CircleAlert, CircleCheck, Clock3, Hand, LoaderCircle, RotateCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useNow } from "@/hooks/use-now";
import { isTerminal } from "@/lib/api/runs";
import type { Run } from "@/lib/api/types";
import { formatElapsed, formatRelative, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Omnicult run states (design direction 7.4). `waiting_for_approval` is not in the API contract yet; the badge supports it
 * so approval runs render correctly the day the contract adds it. `partial` is the API's "completed with gaps".
 */
export type RunState = Run["status"] | "waiting_for_approval";

const STATE: Record<RunState, { label: string; Icon: LucideIcon; className: string; spin?: boolean }> = {
  queued: { label: "Queued", Icon: Clock3, className: "text-info" },
  running: { label: "Running", Icon: LoaderCircle, className: "text-info", spin: true },
  waiting_for_approval: { label: "Waiting for approval", Icon: Hand, className: "text-warning" },
  completed: { label: "Completed", Icon: CircleCheck, className: "text-success" },
  partial: { label: "Completed with gaps", Icon: TriangleAlert, className: "text-warning" },
  failed: { label: "Failed", Icon: CircleAlert, className: "text-danger" },
  cancelled: { label: "Cancelled", Icon: Ban, className: "text-ink-muted" },
};

/** Compact run state: icon and word in a fixed slot, so a changing row keeps its columns (state is held, not reflowed). */
export function RunStatusBadge({ status, className }: { status: RunState; className?: string }) {
  const { label, Icon, className: tone, spin } = STATE[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12.5px] font-medium whitespace-nowrap", tone, className)}>
      <Icon aria-hidden className={cn("size-3.5 shrink-0", spin && "animate-spin motion-reduce:animate-none")} />
      {label}
    </span>
  );
}

type Tone = "info" | "success" | "warning" | "danger" | "neutral";

const TONE: Record<Tone, string> = {
  info: "border-info/25 bg-info-soft/60 [&_[data-icon]]:text-info",
  success: "border-success/25 bg-success-soft/60 [&_[data-icon]]:text-success",
  warning: "border-warning/30 bg-warning-soft/70 [&_[data-icon]]:text-warning",
  danger: "border-danger/25 bg-danger-soft/60 [&_[data-icon]]:text-danger",
  neutral: "border-border bg-surface-muted/60 [&_[data-icon]]:text-ink-secondary",
};

function Panel({
  tone,
  Icon,
  spin,
  title,
  children,
  live = "polite",
}: {
  tone: Tone;
  Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  spin?: boolean;
  title: string;
  children?: ReactNode;
  live?: "polite" | "assertive";
}) {
  return (
    <div role={live === "assertive" ? "alert" : "status"} aria-live={live} className={cn("rounded-md border px-3.5 py-3", TONE[tone])}>
      <div className="flex items-start gap-2.5">
        <span data-icon className="mt-0.5 shrink-0">
          <Icon aria-hidden className={cn("size-4", spin && "animate-spin")} />
        </span>
        <div className="min-w-0 flex-1 space-y-1 text-sm">
          <p className="font-medium text-ink">{title}</p>
          {children}
        </div>
      </div>
    </div>
  );
}

function Meta({ children }: { children: ReactNode }) {
  return <p className="text-xs text-ink-secondary tabular-nums">{children}</p>;
}

/**
 * Honest status for a long-running operation: stage and message from the backend, real elapsed
 * time, and the error as reported. Never a fabricated percentage.
 */
export function RunStatusPanel({ run, operation, onRetry }: { run: Run | undefined; operation: string; onRetry?: () => void }) {
  const active = !run || !isTerminal(run.status);
  const now = useNow(active);

  if (!run) {
    return <Panel tone="info" Icon={LoaderCircle} spin title={operation}><Meta>Waiting for the first status update…</Meta></Panel>;
  }

  const start = Date.parse(run.started_at ?? run.created_at);
  const end = run.completed_at ? Date.parse(run.completed_at) : now;
  const elapsed = formatElapsed(end - start);
  const demo = run.mode === "demo" && <Meta>Demo run: labeled fixtures only; no external provider was called.</Meta>;
  const stage = run.progress && run.progress.stage !== "completed" ? humanize(run.progress.stage) : null;

  switch (run.status) {
    case "queued":
      return (
        <Panel tone="info" Icon={LoaderCircle} spin title={`${operation}: queued`}>
          <Meta>Waiting to start · {elapsed}</Meta>
          {demo}
        </Panel>
      );
    case "running":
      return (
        <Panel tone="info" Icon={LoaderCircle} spin title={`${operation}: running`}>
          {run.progress?.message && <p className="text-ink">{run.progress.message}</p>}
          <Meta>
            {stage && <>Stage: {stage} · </>}
            {run.progress && <>{run.progress.completed_steps} of {run.progress.total_steps} stages done · </>}
            {elapsed} elapsed
          </Meta>
          {demo}
        </Panel>
      );
    case "completed":
      return (
        <Panel tone="success" Icon={CircleCheck} title={`${operation}: completed`}>
          <Meta>
            Finished {formatRelative(run.completed_at)} · took {elapsed}
          </Meta>
          {demo}
        </Panel>
      );
    case "partial":
      return (
        <Panel tone="warning" Icon={TriangleAlert} title={`${operation}: partially completed`}>
          <p className="text-ink">
            Some stages did not finish. The saved result is available, and its limitations name what is missing.
          </p>
          {run.error && <p className="text-ink">{run.error.message}</p>}
          <Meta>
            {run.error?.stage && <>Incomplete stage: {humanize(run.error.stage)} · </>}
            took {elapsed}
          </Meta>
          {demo}
        </Panel>
      );
    case "failed":
      return (
        <Panel tone="danger" Icon={CircleAlert} title={`${operation}: failed`} live="assertive">
          <p className="text-ink">{run.error?.message ?? "The run failed without an error message."}</p>
          <Meta>
            {run.error?.stage && <>Failed at: {humanize(run.error.stage)} · </>}
            {run.error && <span className="font-mono">{run.error.code}</span>}
          </Meta>
          {run.error?.retryable && onRetry ? (
            <Button size="sm" variant="outline" className="mt-1" onClick={onRetry}>
              <RotateCw aria-hidden />
              Retry
            </Button>
          ) : run.error && !run.error.retryable ? (
            <Meta>This failure is not retryable as-is.</Meta>
          ) : null}
        </Panel>
      );
    case "cancelled":
      return (
        <Panel tone="neutral" Icon={Ban} title={`${operation}: cancelled`}>
          {run.error && <p className="text-ink">{run.error.message}</p>}
          <Meta>Stopped after {elapsed}</Meta>
        </Panel>
      );
  }
}
