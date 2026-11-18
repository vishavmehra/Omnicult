"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { RoleMark } from "@/components/creative/role-mark";
import { WorkspaceFeatureChips } from "@/components/shell/feature-links";
import { WORKSPACES, type WorkspaceKey } from "@/components/shell/workspaces";
import { sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, CampaignContent, ContentVersion, RunType } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";

/** Workspace title block: the workspace name in the display face, its job in one line, then campaign facts. No eyebrow. */
export function WorkspaceHeader({ workspace, children, actions }: { workspace: WorkspaceKey; children?: ReactNode; actions?: ReactNode }) {
  const ws = WORKSPACES[workspace];
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-5">
      <div className="min-w-0 space-y-1.5">
        <div className="flex items-center gap-3">
          {/* The workspace's clay mark in its colour role: the same hue as its ambient ground and spine station. */}
          <RoleMark workspace={workspace} size="md" />
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">{ws.label}</h1>
        </div>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">{ws.purpose}</p>
        {children}
        <WorkspaceFeatureChips workspace={workspace} />
      </div>
      {actions &&<div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

/** The campaign facts every workspace shows under its title. */
export function CampaignFacts() {
  const { campaign, project } = useCampaign();
  const regions = campaign.target_markets.map((m) => m.display_name);
  return (
    <p className="type-ledger flex flex-wrap gap-x-4 gap-y-1 pt-1 text-[12.5px] text-ink-muted">
      <span>
        <span className="text-ink-body">{campaign.name}</span> · {project.brand.name}
      </span>
      <span>
        Version <span className="text-ink-body">v{campaign.current_version.version_number}</span> of {campaign.versions.length}
      </span>
      <span>{regions.length ? `Regions: ${regions.join(", ")}` : "No target regions set"}</span>
      <span title={campaign.updated_at}>Updated {formatRelative(campaign.updated_at)}</span>
    </p>
  );
}

/** Ruled definition rows: label column, value column, hairline between entries. */
export function LedgerList({ rows, className }: { rows: { label: string; value: ReactNode; muted?: boolean }[]; className?: string }) {
  return (
    <dl className={cn("ledger-rules rounded-card border border-border bg-surface", className)}>
      {rows.map((r) => (
        <div key={r.label} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">{r.label}</dt>
          <dd className={cn("min-w-0 text-[14px]", r.muted ? "text-ink-muted" : "text-ink-body")}>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Section heading inside a workspace: plain, weighted, with optional trailing meta. */
export function SectionTitle({ children, meta, id }: { children: ReactNode; meta?: ReactNode; id?: string }) {
  return (
    <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
      <h2 id={id} className="text-[15px] font-semibold text-ink">
        {children}
      </h2>
      {meta && <span className="type-meta">{meta}</span>}
    </div>
  );
}

/** A text creative set on the ivory mat. Copy keeps its own `lang` when known so Indic text shapes correctly. */
export function CreativeMat({ content, lang, size = "lg", className }: { content: CampaignContent; lang?: string; size?: "lg" | "sm"; className?: string }) {
  const empty = !content.headline && !content.body && !content.call_to_action;
  return (
    <figure lang={lang} className={cn("creative-mat rounded-card", size === "lg" ? "px-6 py-8 sm:px-10 sm:py-12" : "px-4 py-5", className)}>
      {empty ? (
        <p className="text-[14px] opacity-70">This version has no headline, body or call to action.</p>
      ) : (
        <div className={cn("mx-auto space-y-4", size === "lg" ? "max-w-[46ch]" : "max-w-[40ch]")}>
          {content.headline && <p className={cn("type-title", size === "lg" ? "text-[clamp(26px,3.2vw,40px)]" : "text-[20px]")}>{content.headline}</p>}
          {content.body && <p className={cn("leading-relaxed whitespace-pre-line", size === "lg" ? "text-[16px]" : "text-[13.5px]")}>{content.body}</p>}
          {content.call_to_action && (
            <p className="inline-flex rounded-md border border-current/40 px-3 py-1.5 text-[13.5px] font-semibold">{content.call_to_action}</p>
          )}
        </div>
      )}
    </figure>
  );
}

export const versionsOldestFirst = (c: Campaign): ContentVersion[] => [...c.versions].sort((a, b) => a.version_number - b.version_number);

/** Runs of this campaign, newest first. Polls while one is moving. */
export function useCampaignRuns(types?: RunType[], limit = 30) {
  const { campaign } = useCampaign();
  return useQuery({
    queryKey: ["runs", campaign.project_id, "campaign", campaign.id, limit],
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/v1/projects/{project_id}/runs", {
            params: { path: { project_id: campaign.project_id }, query: { campaign_id: campaign.id, limit } },
          }),
        )
      ).items,
    select: (runs) => (types ? runs.filter((r) => types.includes(r.run_type)) : runs),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 5000 : false),
  });
}

/** Links into the earlier Omnicult research pages for this campaign: real tools, kept working during the migration. */
export function EarlierTools({ tools }: { tools: { segment: string; label: string; note: string }[] }) {
  const { campaign } = useCampaign();
  return (
    <section aria-labelledby="earlier-tools" className="space-y-2">
      <h3 id="earlier-tools" className="text-[13px] font-semibold text-ink">
        Earlier research tools
      </h3>
      <p className="text-[12.5px] text-ink-muted">These pages still work on this campaign while their Omnicult versions are built.</p>
      <ul className="ledger-rules rounded-card border border-border">
        {tools.map((t) => (
          <li key={t.segment}>
            <Link
              href={sectionHref(campaign.project_id, t.segment, campaign.id)}
              className="group flex items-start gap-2 px-3 py-2.5 hover:bg-surface-muted focus-visible:-outline-offset-2"
            >
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium text-ink">{t.label}</span>
                <span className="block text-[12px] text-ink-muted">{t.note}</span>
              </span>
              <ArrowUpRight aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted group-hover:text-rose" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The workspace's built features (only what exists is shown). */
export function FeatureScope({ workspace }: { workspace: WorkspaceKey }) {
  const ws = WORKSPACES[workspace];
  const built = ws.features.filter((f) => f.status === "built");
  return (
    <section aria-label={`${ws.label} features`} className="space-y-2">
      <h3 className="text-[13px] font-semibold text-ink">What {ws.label} covers</h3>
      <ul className="flex flex-wrap gap-1.5">
        {built.map((f) => (
          <li key={f.id} title={f.note} className="rounded-stamp border border-border px-1.5 py-0.5 text-[12px] text-ink-secondary">
            {f.name}
          </li>
        ))}
      </ul>
    </section>
  );
}
