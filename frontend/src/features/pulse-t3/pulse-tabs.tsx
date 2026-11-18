"use client";

import type { ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useAlertInbox } from "./api";
import { AlertsTab } from "./alerts-tab";
import { FatigueTab } from "./fatigue-tab";
import { PredictedActualTab } from "./predicted-actual";

/**
 * The Live Pulse tabs: the existing regional dashboard first, then Predicted vs Actual, Alerts and Fatigue Watch. The dashboard
 * is passed in, so this folder never edits it. The Alerts tab carries the number of open alerts.
 */
export function PulseTabs({ campaignId, overview }: { campaignId: string; overview: ReactNode }) {
  const inbox = useAlertInbox(campaignId);
  const open = inbox.data?.open ?? 0;
  return (
    <Tabs defaultValue="overview" className="gap-5">
      <TabsList variant="line" aria-label="Live Pulse" className="h-auto w-full justify-start gap-1 overflow-x-auto border-b border-border pb-1">
        {[
          ["overview", "Overview"],
          ["predicted", "Predicted vs Actual"],
          ["alerts", "Alerts"],
          ["fatigue", "Fatigue Watch"],
        ].map(([value, label]) => (
          <TabsTrigger key={value} value={value} className="h-9 flex-none px-3 text-[14px] after:bottom-[-5px]">
            {label}
            {value === "alerts" && open > 0 && (
              <span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-warning-soft px-1.5 text-[11px] font-semibold text-warning tabular-nums" aria-label={`${open} open`}>
                {open}
              </span>
            )}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="overview">{overview}</TabsContent>
      <TabsContent value="predicted">
        <PredictedActualTab campaignId={campaignId} />
      </TabsContent>
      <TabsContent value="alerts">
        <AlertsTab campaignId={campaignId} />
      </TabsContent>
      <TabsContent value="fatigue">
        <FatigueTab campaignId={campaignId} />
      </TabsContent>
    </Tabs>
  );
}
