"use client";

import { CircleAlert, CircleCheck, CircleDashed, LoaderCircle, RotateCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, type ErrorCode } from "@/lib/api/errors";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

export type Need = { label: ReactNode; met?: boolean };

/**
 * A blank folio: why nothing is here, what this place is for, and what it needs before it can start. `needs` lists
 * prerequisites with their real state (met or not), so the empty state is also a checklist, never a dead end.
 */
export function EmptyState({
  title,
  description,
  needs,
  action,
  className,
}: {
  title: string;
  description: ReactNode;
  needs?: Need[];
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-start gap-3 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-5 py-5", className)}>
      <div className="max-w-prose space-y-1">
        {/* Not a heading: empty states appear under h1, h2, or h3 and must not break the outline. */}
        <p className="text-[15px] font-semibold text-ink">{title}</p>
        <div className="text-[13.5px] leading-relaxed text-ink-secondary">{description}</div>
      </div>
      {needs && needs.length > 0 && (
        <ul className="space-y-1 text-[13px]" aria-label="What this needs">
          {needs.map((n, i) => (
            <li key={i} className="flex items-start gap-2">
              {n.met ? (
                <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />
              ) : (
                <CircleDashed aria-hidden className="mt-0.5 size-3.5 shrink-0 text-ink-muted" />
              )}
              <span className={n.met ? "text-ink-body" : "text-ink-secondary"}>
                <span className="sr-only">{n.met ? "Done: " : "Needed: "}</span>
                {n.label}
              </span>
            </li>
          ))}
        </ul>
      )}
      {action}
    </div>
  );
}

/** Names the actual operation in progress; skeleton rows are reserved for layouts whose shape is known. */
export function LoadingState({ label, className }: { label: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("flex items-center gap-2 px-1 py-6 text-sm text-ink-secondary", className)}>
      <LoaderCircle aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />
      {label}
    </div>
  );
}

type Explanation = { title: string; saved: string; retry: string; next: ReactNode };

const NOTHING_SAVED = "Nothing was saved or started; the API rejected the request before acting on it.";

function explain(code: ErrorCode | "NETWORK_ERROR"): Explanation {
  switch (code) {
    case "NETWORK_ERROR":
      return {
        title: "Could not reach the Omnicult API",
        saved: "The request may not have reached the server. If you were saving a change, reload to check before trying again.",
        retry: "Retrying is safe for viewing data.",
        next: `Check that the backend is running at ${env.apiBaseUrl}.`,
      };
    case "VALIDATION_ERROR":
      return {
        title: "The request was rejected as invalid",
        saved: "Nothing was saved.",
        retry: "Retrying unchanged will fail again.",
        next: "Correct the fields listed below and submit again.",
      };
    case "UNAUTHENTICATED":
      return {
        title: "Your session is missing or has expired",
        saved: NOTHING_SAVED,
        retry: "Retrying will fail until you sign in again.",
        next:
          env.authMode === "firebase" ? (
            <Link className="underline underline-offset-2" href="/login">
              Sign in again
            </Link>
          ) : (
            "Restart the frontend in development auth mode, or check the backend's AUTH_MODE."
          ),
      };
    case "FORBIDDEN":
      return { title: "This action is not permitted", saved: NOTHING_SAVED, retry: "Retrying will not help.", next: "Check that you are working in the right brand and campaign." };
    case "NOT_FOUND":
      return {
        title: "Not found",
        saved: NOTHING_SAVED,
        retry: "Retrying will not help.",
        next: (
          <>
            It may have been archived, or it belongs to another account.{" "}
            <Link className="underline underline-offset-2" href="/app">
              Return to Campaign Desk
            </Link>
            .
          </>
        ),
      };
    case "CONFLICT":
      return {
        title: "This conflicts with the current state",
        saved: "Nothing was changed.",
        retry: "Retrying unchanged will fail again.",
        next: "Demo campaigns and archived brands are read-only. Create a live brand to change content.",
      };
    case "RATE_LIMITED":
      return { title: "Too many active runs", saved: "No new run was started.", retry: "Retry once a running operation finishes.", next: "Each account can run 2 operations at a time." };
    case "PROVIDER_NOT_CONFIGURED":
      return {
        title: "A live provider is not configured",
        saved: "No run was started and nothing was saved.",
        retry: "Retrying will fail until the provider credentials are configured on the backend.",
        next: (
          <>
            Live brands call the configured data and model providers.{" "}
            <Link className="underline underline-offset-2" href="/app">
              Try the demo
            </Link>{" "}
            to explore the workflow on labelled fixtures.
          </>
        ),
      };
    case "UNSUPPORTED_CAPABILITY":
      return { title: "The data sources cannot answer this request", saved: NOTHING_SAVED, retry: "Retrying unchanged will fail again.", next: "Rephrase the request or use different reference terms." };
    case "PROVIDER_ERROR":
    case "PROVIDER_TIMEOUT":
      return { title: "An external provider failed", saved: "The message above states what was saved.", retry: "Retrying is usually safe.", next: "Try again in a moment." };
    case "RUN_FAILED":
    case "RUN_INTERRUPTED":
      return { title: "The workflow did not finish", saved: "The message above states what was saved.", retry: "Retrying is usually safe.", next: "Start the operation again." };
    default:
      return {
        title: "Something went wrong",
        saved: "Unknown. Reload to check before repeating a change.",
        retry: "Retrying may be safe for viewing data.",
        next: "If it keeps happening, share the request id with the team.",
      };
  }
}

/** Explains a failed request: what failed, whether anything was saved, whether retry is safe, and what to do next. */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const apiError = error instanceof ApiError ? error : null;
  const info = explain(apiError?.code ?? "INTERNAL_ERROR");
  const message = apiError?.message ?? (error instanceof Error ? error.message : null);
  return (
    <div role="alert" className={cn("rounded-card border border-danger/35 bg-danger-soft/60 px-4 py-3.5", className)}>
      <div className="flex items-start gap-2.5">
        <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
        <div className="min-w-0 space-y-2 text-sm">
          <div>
            <p className="font-semibold text-ink">{info.title}</p>
            {message && <p className="text-ink">{message}</p>}
          </div>
          {apiError && apiError.details.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink">
              {apiError.details.map((d, i) => (
                <li key={i}>
                  {d.field && <span className="font-mono text-xs">{d.field}: </span>}
                  {d.message}
                </li>
              ))}
            </ul>
          )}
          <dl className="grid gap-x-3 gap-y-0.5 text-[13px] text-ink-secondary sm:grid-cols-[auto_1fr]">
            <dt className="font-medium text-ink">Saved</dt>
            <dd>{info.saved}</dd>
            <dt className="font-medium text-ink">Retry</dt>
            <dd>{info.retry}</dd>
            <dt className="font-medium text-ink">Next</dt>
            <dd>{info.next}</dd>
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            {onRetry && (
              <Button size="sm" variant="outline" onClick={onRetry}>
                <RotateCw aria-hidden />
                Try again
              </Button>
            )}
            {apiError?.requestId && <span className="font-mono text-[11px] text-ink-secondary">request {apiError.requestId}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
