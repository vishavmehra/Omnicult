"use client";

/**
 * Route handoff between the landing page, the sign-in page and the app. The ground (body::before) never unmounts, so the scene is
 * continuous by construction; this module adds two things on top: a View Transition crossfade for the page content (when
 * the browser supports it and motion is allowed), and a record of which zone the visitor came from, so the app shell can
 * play its arrival only when someone actually arrives from outside the app.
 */

export type Zone = "landing" | "cover" | "app";

let lastZone: Zone | null = null;
let pending: (() => void) | null = null;

export function zoneOf(pathname: string): Zone {
  if (pathname === "/") return "landing";
  if (pathname.startsWith("/login")) return "cover";
  return "app";
}

/** Read during render: true when the previous route was the landing page or the sign-in cover. */
export function arrivingFromOutside() {
  return lastZone === "landing" || lastZone === "cover";
}

/** Called by ZoneMarker after each route commit. Resolves a pending View Transition. */
export function routeCommitted(pathname: string) {
  lastZone = zoneOf(pathname);
  const resolve = pending;
  pending = null;
  resolve?.();
}

type Router = { push(href: string): void };

/** Navigate with a content crossfade over the continuous field. Falls back to a plain push. */
export function navigate(router: Router, href: string) {
  const doc = document as Document & { startViewTransition?: (update: () => Promise<void>) => unknown };
  if (!doc.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    router.push(href);
    return;
  }
  doc.startViewTransition(
    () =>
      new Promise<void>((resolve) => {
        pending = resolve;
        router.push(href);
        // Never hold the page frozen: give up on the crossfade if the route has not committed in time.
        window.setTimeout(() => {
          if (pending === resolve) {
            pending = null;
            resolve();
          }
        }, 1800);
      }),
  );
}
