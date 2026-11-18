"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import type { ProofView } from "./types";

export const VIEWS: { key: ProofView; label: string }[] = [
  { key: "report", label: "Report" },
  { key: "history", label: "Run history" },
  { key: "health", label: "Data health" },
  { key: "map", label: "Evidence map" },
  { key: "search", label: "Search" },
];

/**
 * The open view, report and claim live in the URL, so a claim or a snapshot can be linked to and Back closes the drawer.
 * Updates use the History API directly (Next.js keeps useSearchParams in step), so no page is re-fetched.
 */
export function useProofParams() {
  const params = useSearchParams();
  const pathname = usePathname();
  const raw = params.get("view");
  const view = (VIEWS.some((v) => v.key === raw) ? raw : "report") as ProofView;

  const set = useCallback(
    (patch: Record<string, string | null>, mode: "push" | "replace" = "push") => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      const qs = next.toString();
      window.history[mode === "push" ? "pushState" : "replaceState"](null, "", qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname],
  );

  return { view, reportId: params.get("report"), claimId: params.get("claim"), set };
}
