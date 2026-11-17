"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { routeCommitted, zoneOf } from "./transition";

/**
 * Marks <html data-zone="landing|cover|app"> so the continuous ground (body::before in globals.css) can calm down inside
 * the app, and records the zone a visitor came from for the app shell's arrival. Renders nothing.
 */
export function ZoneMarker() {
  const pathname = usePathname();
  useEffect(() => {
    document.documentElement.setAttribute("data-zone", zoneOf(pathname));
    routeCommitted(pathname);
  }, [pathname]);
  return null;
}
