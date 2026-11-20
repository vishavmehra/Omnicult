"use client";

import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { STATUS_WORD, activeFeatureIds, bestMatches, markFeatureNav } from "./feature-nav";
import { WORKSPACES, featureHref, isOpenable, workspaceViews, type Feature, type WorkspaceKey } from "./workspaces";

/** One feature as a navigation row. Built features go to their deep link; any other is shown muted and is not a link. */
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
  if (!isOpenable(feature) || !href) {
    return (
      <span title={feature.note} className={cn(className, mutedClassName, "cursor-default")}>
        {name}
        {trailing}
      </span>
    );
  }
  const style = cn(className, feature.status === "roadmap" ? mutedClassName : active ? activeClassName : idleClassName);
  return (
    <Link
      href={href}
      title={feature.note}
      aria-current={active ? "page" : undefined}
      className={style}
      onClick={(e) => {
        onNavigate?.();
        if (!e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) markFeatureNav(href);
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

/** A workspace's places as spine rows: the same list, names and order as its "In this workspace" chips, so the two never differ. */
export function WorkspaceViewRows({ workspace, campaignId, onNavigate }: { workspace: WorkspaceKey; campaignId: string; onNavigate?: () => void }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const views = workspaceViews(workspace);
  const hrefs = views.map((v) => v.href(campaignId));
  const active = bestMatches(hrefs, pathname, search);
  const keep = WORKSPACES[workspace].keepParams ?? [];
  return views.map((v, i) => {
    const href = withKept(hrefs[i], pathname, search, keep);
    const isOpen = active.has(i);
    return (
      <li key={hrefs[i]} className="relative">
        <Link
          href={href}
          title={v.title}
          aria-current={isOpen ? "page" : undefined}
          className={cn(
            "flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[13px] transition-colors duration-150 max-lg:h-10",
            isOpen
              ? "bg-surface-muted/80 font-medium text-ink before:absolute before:top-1.5 before:bottom-1.5 before:-left-[6.5px] before:w-0.5 before:rounded-full before:bg-pop"
              : "text-ink-secondary hover:bg-surface-muted/70 hover:text-ink",
          )}
          onClick={(e) => {
            onNavigate?.();
            if (!e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) markFeatureNav(href);
          }}
        >
          <span className="min-w-0 truncate">{v.name}</span>
        </Link>
      </li>
    );
  });
}

/** The active feature ids for the address in the bar, shared by the spine and the header chips. */
export function useActiveFeatureIds(campaignId: string | null) {
  const pathname = usePathname();
  const search = useSearchParams();
  return activeFeatureIds(pathname, search, campaignId);
}

/** The same page with the query values that belong to the open page (the selected state, the open report) carried to the new tab. */
function withKept(href: string, pathname: string, search: { get(name: string): string | null }, keep: string[]) {
  const url = new URL(href, "http://omnicult.local");
  if (url.pathname !== pathname) return href;
  for (const key of keep) {
    const value = search.get(key);
    if (value !== null && !url.searchParams.has(key)) url.searchParams.set(key, value);
  }
  return `${url.pathname}${url.search}`;
}

/**
 * "In this workspace": one chip for every place the workspace opens, the only row of tabs a workspace page has. Features that
 * open the same place share a chip. A jump within the page switches the view in place (the page reads its tab from the
 * address on every render); a jump to another page navigates. On a phone the row scrolls sideways and keeps the open chip in sight.
 */
export function WorkspaceFeatureChips({ workspace }: { workspace: WorkspaceKey }) {
  const { campaignId = null } = useParams<{ campaignId?: string }>();
  const pathname = usePathname();
  const search = useSearchParams();
  const row = useRef<HTMLElement>(null);
  const views = workspaceViews(workspace);
  const hrefs = campaignId ? views.map((v) => v.href(campaignId)) : [];
  const active = bestMatches(hrefs, pathname, search);
  const openAt = [...active].join();
  useEffect(() => {
    const nav = row.current;
    const chip = nav?.querySelector<HTMLElement>("[aria-current=page]");
    if (nav && chip && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = chip.offsetLeft - (nav.clientWidth - chip.offsetWidth) / 2;
  }, [openAt]);
  if (!campaignId || views.length === 0) return null;
  const keep = WORKSPACES[workspace].keepParams ?? [];
  return (
    <nav
      ref={row}
      aria-label="In this workspace"
      className="relative flex items-center gap-1.5 pt-3 max-sm:overflow-x-auto max-sm:pr-6 max-sm:[mask-image:linear-gradient(to_right,black_calc(100%-1.5rem),transparent)] max-sm:[scrollbar-width:none] sm:flex-wrap"
    >
      <span className="mr-1 shrink-0 text-[12.5px] text-ink-muted">In this workspace</span>
      {views.map((v, i) => {
        const here = new URL(hrefs[i], "http://omnicult.local").pathname === pathname;
        const isOpen = active.has(i);
        return (
          <Link
            key={hrefs[i]}
            href={withKept(hrefs[i], pathname, search, keep)}
            title={v.title}
            replace={here}
            scroll={!here}
            aria-current={isOpen ? "page" : undefined}
            className={cn(
              "inline-flex h-7 shrink-0 items-center rounded-lg border border-border px-2.5 text-[12.5px] whitespace-nowrap transition-colors duration-150 max-sm:h-9 max-sm:px-3",
              isOpen ? "border-border-strong bg-surface-raised text-ink shadow-clay" : "text-ink-secondary hover:bg-surface-muted hover:text-ink",
            )}
          >
            {v.name}
          </Link>
        );
      })}
    </nav>
  );
}
