"use client";

import type { ReactNode } from "react";

import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { useCampaignDirectory } from "@/features/desk/use-campaign-directory";

/** The shell for pages that sit beside the workspaces (Usage, Roadmap): the spine links to the most recent campaign. */
export function PlatformShell({ active, children }: { active: "usage" | "roadmap"; children: ReactNode }) {
  const dir = useCampaignDirectory();
  return (
    <WorkspaceShell campaignId={dir.campaigns[0]?.id ?? null} active={active}>
      {children}
    </WorkspaceShell>
  );
}
