"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

export type LabTab = "quick" | "study" | "ask" | "risk";
export const LAB_TABS: LabTab[] = ["quick", "study", "ask", "risk"];

/**
 * The tab and the selected run live in the URL (`?tab=risk&run=<id>`), so a refresh keeps the place and Launch Room or
 * Proof Vault can link straight to a result. `participant` and `q` carry an Ask the Panel hand-off.
 */
export function useLabLocation() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const raw = params.get("tab");
  const tab: LabTab = LAB_TABS.includes(raw as LabTab) ? (raw as LabTab) : "quick";

  const go = useCallback(
    (next: Partial<{ tab: LabTab; run: string | null; participant: string | null; q: string | null }>) => {
      const p = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(next)) {
        if (v === null || v === undefined || v === "") p.delete(k);
        else p.set(k, v);
      }
      const query = p.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return {
    tab,
    runId: params.get("run"),
    participantId: params.get("participant"),
    question: params.get("q"),
    /** Switch tab; the selected run, participant and question belong to a tab, so they are cleared unless given. */
    setTab: (next: LabTab) => go({ tab: next, run: null, participant: null, q: null }),
    selectRun: (run: string | null) => go({ run, participant: null, q: null }),
    go,
  };
}
