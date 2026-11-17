import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { CampaignShell } from "@/features/workspaces/campaign-context";

// The shell reads route params on the client (runtime data under Cache Components). Pages below it opt out of
// instant-navigation validation with `export const instant = false`, as the /projects/[projectId] pages do.
export default function CampaignLayout({ children }: LayoutProps<"/app/c/[campaignId]">) {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-canvas"><LoadingState label="Opening the campaign…" /></div>}>
      <CampaignShell>{children}</CampaignShell>
    </Suspense>
  );
}
