"use client";

import { BellRing, ChartNoAxesCombined, GitCompareArrows, MessagesSquare, Newspaper, TrendingDown } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ComponentType } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { asPulseView, PULSE_VIEWS, type PulseView } from "./logic";

const ICON: Record<PulseView, ComponentType> = {
  overview: ChartNoAxesCombined,
  predicted: GitCompareArrows,
  alerts: BellRing,
  fatigue: TrendingDown,
  comments: MessagesSquare,
  digest: Newspaper,
};

/** The Live Pulse view in the address (`?view=comments`), so a view can be linked to, reloaded and opened from a digest line. */
export function usePulseView(): PulseView {
  return asPulseView(useSearchParams().get("view"));
}

/** One row of tabs for the Live Pulse workspace. Add a view by adding it to PULSE_VIEWS (logic.ts) and rendering it where the view is read. */
export function PulseTabs({ view }: { view: PulseView }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  function go(next: PulseView) {
    const q = new URLSearchParams(params.toString());
    if (next === "overview") q.delete("view");
    else q.set("view", next);
    const qs = q.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <Tabs value={view} onValueChange={(v) => go(asPulseView(String(v)))} className="mb-6">
      <TabsList variant="line" aria-label="Live Pulse views" className="h-auto w-full max-w-full justify-start gap-x-0.5 overflow-x-auto border-b border-border pb-1.5 [scrollbar-width:none]">
        {PULSE_VIEWS.map(({ key, label }) => {
          const Icon = ICON[key];
          return (
            <TabsTrigger key={key} value={key} className="h-9 min-w-11 flex-none px-2.5 text-[14px] sm:px-3">
              <Icon aria-hidden />
              {label}
            </TabsTrigger>
          );
        })}
      </TabsList>
    </Tabs>
  );
}
