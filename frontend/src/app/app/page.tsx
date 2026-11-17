import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { TodayView } from "@/features/desk/today";

export const metadata: Metadata = { title: "Campaign Desk" };

// TodayView reads ?new= (useSearchParams), which is runtime data under Cache Components.
export default function CampaignDeskHome() {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-canvas"><LoadingState label="Opening Campaign Desk…" /></div>}>
      <TodayView />
    </Suspense>
  );
}
