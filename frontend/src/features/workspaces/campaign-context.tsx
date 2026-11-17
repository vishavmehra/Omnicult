"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useSelectedLayoutSegment } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { isWorkspaceKey } from "@/components/shell/workspaces";
import { ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, Project } from "@/lib/api/types";

export const campaignKeys = {
  detail: (id: string) => ["campaign", id] as const,
};

type CampaignContextValue = { campaign: Campaign; project: Project };
const CampaignContext = createContext<CampaignContextValue | null>(null);

/** The open campaign and its brand. Only available under /app/c/[campaignId], which handles loading and errors. */
export function useCampaign(): CampaignContextValue {
  const ctx = useContext(CampaignContext);
  if (!ctx) throw new Error("useCampaign must be used inside /app/c/[campaignId].");
  return ctx;
}

/** Loads the campaign, then its brand (API project), and frames every workspace page in the shell. */
export function CampaignShell({ children }: { children: ReactNode }) {
  const { campaignId } = useParams<{ campaignId: string }>();
  const segment = useSelectedLayoutSegment();
  const active = isWorkspaceKey(segment) ? segment : "desk";

  const campaign = useQuery({
    queryKey: campaignKeys.detail(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}", { params: { path: { campaign_id: campaignId } } })),
  });
  const projectId = campaign.data?.project_id;
  const project = useQuery({
    queryKey: ["project", projectId],
    enabled: Boolean(projectId),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId! } } })),
  });

  const error = campaign.error ?? project.error;
  if (error || !campaign.data || !project.data) {
    return (
      <WorkspaceShell campaignId={campaignId} active={active}>
        {error ? (
          <ErrorState
            error={error}
            onRetry={() => {
              void campaign.refetch();
              void project.refetch();
            }}
          />
        ) : (
          <LoadingState label="Opening the campaign…" />
        )}
      </WorkspaceShell>
    );
  }

  return (
    <CampaignContext.Provider value={{ campaign: campaign.data, project: project.data }}>
      <WorkspaceShell campaignId={campaignId} active={active} mode={project.data.mode}>
        {children}
      </WorkspaceShell>
    </CampaignContext.Provider>
  );
}
