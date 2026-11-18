import { PLATFORM_FEATURES, WORKSPACES, WORKSPACE_ORDER, featureHref, type Feature } from "./workspaces";

/** Every feature in catalogue order: the seven workspaces, then the platform features. */
export const ALL_FEATURES: Feature[] = [...WORKSPACE_ORDER.flatMap((key) => WORKSPACES[key].features), ...PLATFORM_FEATURES];

/** The one word shown on a feature that cannot be opened yet. */
export const STATUS_WORD = { built: "", in_progress: "Building", roadmap: "Roadmap" } as const;

type Search = { get(name: string): string | null };

/** How many query values a link pins down when the address is on it, or null when the address is somewhere else. */
function matchSize(href: string, pathname: string, search: Search): number | null {
  const url = new URL(href, "http://omnicult.local");
  const wanted = [...url.searchParams];
  return url.pathname === pathname && wanted.every(([key, value]) => search.get(key) === value) ? wanted.length : null;
}

/**
 * Ids of the built features the current address is showing. The most specific links win, and features that share a link
 * all count (State Profile and Evidence Meter live on one view). A default tab links to the bare workspace, so it matches
 * only when nothing narrower does.
 */
export function activeFeatureIds(pathname: string, search: Search, campaignId: string | null): Set<number> {
  let best = -1;
  let ids: number[] = [];
  for (const feature of ALL_FEATURES) {
    const href = feature.status === "built" ? featureHref(feature, campaignId) : null;
    const size = href ? matchSize(href, pathname, search) : null;
    if (size === null) continue;
    if (size > best) [best, ids] = [size, []];
    if (size === best) ids.push(feature.id);
  }
  return new Set(ids);
}

// A link to another tab of the page you are already on only changes the query string. Some workspaces read their tab from
// the address once, when they mount, so the shell remounts the page after such a jump. The mark says which jump was ours.
let latest: { id: number; href: string } | null = null;
let counter = 0;
export const markFeatureNav = (href: string) => {
  latest = { id: ++counter, href };
};
export const latestFeatureNav = () => latest;

/** True when the address has arrived at the marked jump (same page, all of its query values present). */
export const arrivedAt = (mark: { href: string }, pathname: string, search: Search) => matchSize(mark.href, pathname, search) !== null;
