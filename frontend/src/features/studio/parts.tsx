"use client";

import { Check, CircleAlert, CircleX, Lock, LockOpen, ShieldAlert, type LucideIcon } from "lucide-react";
import { createContext, useContext, type ComponentProps, type ReactNode } from "react";

import { ErrorState } from "@/components/states";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import type { RegionLanguage } from "./types";

/** What every Studio part needs to know about the open campaign. */
export type StudioContextValue = {
  campaignId: string;
  projectId: string;
  workspaceId: string | null;
  /** True for a demo brand: runs answer from labelled fixtures and may refuse prompts they have no fixture for. */
  demo: boolean;
  /** ISO 639-1 code to English name, from the region reference list. */
  languageNames: Map<string, string>;
  /** Every language the reference list names (code, names, script), once each. */
  languages: RegionLanguage[];
};

const StudioContext = createContext<StudioContextValue | null>(null);
export const StudioProvider = StudioContext.Provider;
export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error("useStudio must be used inside the Creative Studio workspace.");
  return ctx;
}

export const languageLabel = (names: Map<string, string>, code: string | null | undefined) => (code ? (names.get(code) ?? code.toUpperCase()) : "No language set");

/** A native select in the control vocabulary of the inputs (32px, 9px corners, well tone). Native keeps keyboard and phone behaviour. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      {...props}
      className={cn(
        "h-8 w-full min-w-0 rounded-lg border border-input bg-surface-raised px-2 text-sm text-ink shadow-well transition-colors outline-none focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-surface-muted",
        className,
      )}
    />
  );
}

/** A status as icon, word and colour together (the Word-and-Icon rule). */
export function Status({ tone, Icon, children, className }: { tone: "success" | "warning" | "danger" | "neutral"; Icon: LucideIcon; children: ReactNode; className?: string }) {
  const color = { success: "text-success", warning: "text-warning", danger: "text-danger", neutral: "text-ink-secondary" }[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium whitespace-nowrap", color, className)}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

export const Passed = ({ children = "Passed" }: { children?: ReactNode }) => (
  <Status tone="success" Icon={Check}>
    {children}
  </Status>
);
export const Failed = ({ children = "Failed" }: { children?: ReactNode }) => (
  <Status tone="danger" Icon={CircleX}>
    {children}
  </Status>
);

/** The lock's state as icon and word. */
export const LockState = ({ locked }: { locked: boolean }) =>
  locked ? (
    <Status tone="warning" Icon={Lock}>
      Locked
    </Status>
  ) : (
    <Status tone="neutral" Icon={LockOpen}>
      Unlocked
    </Status>
  );

/**
 * A failed write, stated plainly. A 409 is a refusal by the rules (a locked element, a chip already applied, an element that
 * is no longer there): it says what was refused and that nothing changed. A 403 says the role cannot write. Every other
 * failure (provider not configured, provider error, network) goes through the shared ErrorState.
 */
export function MutationError({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  if (error instanceof ApiError && (error.code === "CONFLICT" || error.code === "FORBIDDEN")) {
    const refusal = error.code === "CONFLICT";
    return (
      <div role="alert" className={cn("rounded-lg border border-warning/40 bg-warning-soft/60 px-3.5 py-3", className)}>
        <div className="flex items-start gap-2.5">
          {refusal ? <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" /> : <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />}
          <div className="min-w-0 space-y-1 text-[13.5px]">
            <p className="font-semibold text-ink">{refusal ? "Refused" : "Your role cannot make this change"}</p>
            <p className="text-ink">{error.message}</p>
            {error.details.some((d) => d.field !== "operation") && (
              <ul className="list-disc pl-5 text-[13px] text-ink-body">
                {error.details.filter((d) => d.field !== "operation").map((d, i) => (
                  <li key={i}>
                    {d.field && <span className="font-mono text-xs">{d.field}: </span>}
                    {d.message}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[12.5px] text-ink-secondary">Nothing was changed.</p>
            {error.requestId && <p className="font-mono text-[11px] text-ink-muted">request {error.requestId}</p>}
          </div>
        </div>
      </div>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} className={className} />;
}
