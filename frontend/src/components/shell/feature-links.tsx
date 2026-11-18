"use client";

import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { useOpenCommandBar } from "@/features/desk/command-bar";
import { DemoSignInError, useStartDemo } from "@/features/desk/use-start-demo";
import { cn } from "@/lib/utils";

import { STATUS_WORD, activeFeatureIds, markFeatureNav } from "./feature-nav";
import { WORKSPACES, featureHref, isOpenable, type Feature, type WorkspaceKey } from "./workspaces";

/** A feature that does something (opens the Command Bar, starts the demo) instead of going somewhere. */
function ActionButton({ feature, className, onDone, children }: { feature: Feature; className: string; onDone?: () => void; children: ReactNode }) {
  const openBar = useOpenCommandBar();
  const demo = useStartDemo();
  return (
    <button
      type="button"
      className={className}
      disabled={feature.action === "demo" && demo.isPending}
      aria-keyshortcuts={feature.action === "command-bar" ? "Control+K Meta+K" : undefined}
      onClick={() => {
        if (feature.action === "command-bar") {
          openBar?.(true);
          onDone?.();
          return;
        }
        demo.mutate(undefined, {
          onSuccess: onDone,
          onError: (error) => toast.error(error instanceof DemoSignInError ? error.message : "The demo could not be prepared. Try again in a moment."),
        });
      }}
    >
      {children}
    </button>
  );
}

/**
 * One feature as a navigation row or chip. Built features go to their deep link (or run their action); features still being
 * built are shown but are not links; roadmap features, muted, point at the roadmap page.
 */
export function FeatureLink({
  feature,
  campaignId,
  active,
  className,
  activeClassName,
  idleClassName,
  mutedClassName,
  onNavigate,
  trailing,
}: {
  feature: Feature;
  campaignId: string | null;
  active: boolean;
  className: string;
  activeClassName: string;
  idleClassName: string;
  mutedClassName: string;
  onNavigate?: () => void;
  /** Extra content after the name (the status word on a row). */
  trailing?: ReactNode;
}) {
  const href = featureHref(feature, campaignId);
  const name = <span className="min-w-0 truncate">{feature.name}</span>;
  if (!isOpenable(feature) || (!href && !feature.action)) {
    return (
      <span title={feature.note} className={cn(className, mutedClassName, "cursor-default")}>
        {name}
        {trailing}
      </span>
    );
  }
  const style = cn(className, feature.status === "roadmap" ? mutedClassName : active ? activeClassName : idleClassName);
  if (feature.action) {
    return (
      <ActionButton feature={feature} className={cn(style, "text-left")} onDone={onNavigate}>
        {name}
        {trailing}
      </ActionButton>
    );
  }
  return (
    <Link
      href={href!}
      title={feature.note}
      aria-current={active ? "page" : undefined}
      className={style}
      onClick={(e) => {
        onNavigate?.();
        if (!e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) markFeatureNav(href!);
      }}
    >
      {name}
      {trailing}
    </Link>
  );
}

/** Spine row for one feature: its name, and on the right the one word that says why it cannot be opened yet. */
export function FeatureRow({ feature, campaignId, active, onNavigate }: { feature: Feature; campaignId: string | null; active: boolean; onNavigate?: () => void }) {
  const word = STATUS_WORD[feature.status];
  const openable = isOpenable(feature);
  return (
    <li className="relative">
      <FeatureLink
        feature={feature}
        campaignId={campaignId}
        active={active}
        onNavigate={onNavigate}
        className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] transition-colors duration-150 max-lg:h-10"
        activeClassName="bg-surface-muted/80 font-medium text-ink before:absolute before:top-1.5 before:bottom-1.5 before:-left-[6.5px] before:w-0.5 before:rounded-full before:bg-pop"
        idleClassName="text-ink-secondary hover:bg-surface-muted/70 hover:text-ink"
        mutedClassName={openable ? "text-ink-muted hover:bg-surface-muted/70 hover:text-ink-secondary" : "text-ink-muted"}
        trailing={word ? <span className="ml-auto shrink-0 text-[11px] text-ink-muted">{word}</span> : undefined}
      />
    </li>
  );
}

/** The active feature ids for the address in the bar, shared by the spine and the header chips. */
export function useActiveFeatureIds(campaignId: string | null) {
  const pathname = usePathname();
  const search = useSearchParams();
  return activeFeatureIds(pathname, search, campaignId);
}

/** "In this workspace": the built features of the open workspace as chips, each one click to its tab or view. */
export function WorkspaceFeatureChips({ workspace }: { workspace: WorkspaceKey }) {
  const { campaignId = null } = useParams<{ campaignId?: string }>();
  const active = useActiveFeatureIds(campaignId);
  const features = WORKSPACES[workspace].features.filter((f) => f.status === "built" && (f.href || f.action));
  if (!campaignId || features.length === 0) return null;
  return (
    <nav aria-label="In this workspace" className="flex flex-wrap items-center gap-1.5 pt-2.5">
      <span className="mr-1 text-[12.5px] text-ink-muted">In this workspace</span>
      {features.map((f) => (
        <FeatureLink
          key={f.id}
          feature={f}
          campaignId={campaignId}
          active={active.has(f.id)}
          className="inline-flex h-7 items-center rounded-lg border border-border px-2.5 text-[12.5px] transition-colors duration-150"
          activeClassName="border-border-strong bg-surface-raised text-ink shadow-clay"
          idleClassName="text-ink-secondary hover:bg-surface-muted hover:text-ink"
          mutedClassName="text-ink-muted"
        />
      ))}
    </nav>
  );
}
