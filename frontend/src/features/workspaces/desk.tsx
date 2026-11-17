"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Lock, PencilLine } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { Button } from "@/components/ui/button";
import { CampaignForm, CAMPAIGN_TYPES, WEIGHT_FIELDS } from "@/features/project/campaign-form";
import { sectionHref } from "@/features/project/workflow";
import { formatDateTime } from "@/lib/format";

import { campaignKeys, useCampaign } from "./campaign-context";
import { CampaignFacts, CreativeMat, FeatureScope, LedgerList, SectionTitle, WorkspaceHeader } from "./parts";

function Terms({ terms, empty }: { terms: string[]; empty: string }) {
  if (!terms.length) return <span className="text-ink-muted">{empty}</span>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {terms.map((t) => (
        <li key={t} className="rounded-stamp border border-border-strong/45 bg-surface-raised px-1.5 py-0.5 text-[12.5px] text-ink">
          {t}
        </li>
      ))}
    </ul>
  );
}

/** Brand Kit summary from the brand record (API project.brand), in the context panel next to the brief. */
function BrandKitPanel() {
  const { project, campaign } = useCampaign();
  const b = project.brand;
  return (
    <ContextPanel title="Brand Kit">
      <div className="space-y-1">
        <p className="type-title text-[22px] text-ink">{b.name}</p>
        {b.positioning && <p className="text-[13.5px] text-ink-body">{b.positioning}</p>}
        {b.description && !b.positioning && <p className="text-[13.5px] text-ink-body">{b.description}</p>}
      </div>
      <dl className="space-y-3.5 text-[13.5px]">
        <div className="space-y-1.5">
          <dt className="type-meta">Voice</dt>
          <dd>
            <Terms terms={b.voice} empty="No voice attributes yet" />
          </dd>
        </div>
        <div className="space-y-1.5">
          <dt className="type-meta inline-flex items-center gap-1">
            <Lock aria-hidden className="size-3" />
            Protected terms, never changed in adaptations
          </dt>
          <dd>
            <Terms terms={b.protected_terms} empty="None protected" />
          </dd>
        </div>
        <div className="space-y-1.5">
          <dt className="type-meta">Preferred terms</dt>
          <dd>
            <Terms terms={b.preferred_terms} empty="None listed" />
          </dd>
        </div>
        <div className="space-y-1.5">
          <dt className="type-meta">Prohibited terms</dt>
          <dd>
            <Terms terms={b.prohibited_terms} empty="None listed" />
          </dd>
        </div>
        {b.target_audience && (
          <div className="space-y-1">
            <dt className="type-meta">Target audience (stated assumption)</dt>
            <dd className="text-ink-body">{b.target_audience}</dd>
          </div>
        )}
      </dl>
      <p className="text-[12.5px] text-ink-muted">
        Logo, colours, fonts, product images and the Brand Glossary (spelling by script, pronunciation, do-not-translate) are not in the brand record yet.
      </p>
      <Link href={sectionHref(campaign.project_id, "brand", campaign.id)} className="inline-flex text-[13.5px] font-medium text-rose hover:underline">
        Edit the brand record
      </Link>
      <FeatureScope workspace="desk" />
    </ContextPanel>
  );
}

/** Campaign Desk for one campaign: the brief every other workspace reads, and the Brand Kit beside it. */
export function DeskWorkspace() {
  const { campaign, project } = useCampaign();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const content = campaign.current_version.content;
  const type = CAMPAIGN_TYPES.find((t) => t.value === campaign.campaign_type)?.label ?? campaign.campaign_type;
  const notYet = "Not in the brief contract yet";

  return (
    <>
      <WorkspaceHeader
        workspace="desk"
        actions={
          !editing && (
            <Button variant="outline" onClick={() => setEditing(true)}>
              <PencilLine aria-hidden />
              Edit brief
            </Button>
          )
        }
      >
        <CampaignFacts />
      </WorkspaceHeader>

      {editing ? (
        <section aria-labelledby="edit-brief" className="rounded-card border border-border bg-surface p-5 sm:p-6">
          <SectionTitle id="edit-brief">Edit the brief</SectionTitle>
          <CampaignForm
            projectId={campaign.project_id}
            campaign={campaign}
            demo={project.mode === "demo"}
            onCancel={() => setEditing(false)}
            onDone={() => {
              void queryClient.invalidateQueries({ queryKey: campaignKeys.detail(campaign.id) });
              setEditing(false);
            }}
          />
        </section>
      ) : (
        <div className="grid gap-8 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <section aria-labelledby="brief">
            <SectionTitle id="brief" meta="Shared by all seven workspaces">
              Campaign brief
            </SectionTitle>
            <LedgerList
              rows={[
                { label: "Campaign", value: campaign.name },
                { label: "Brand", value: project.brand.name },
                { label: "Format", value: type },
                { label: "Objective", value: campaign.objective ?? "No objective stated", muted: !campaign.objective },
                {
                  label: "Target regions",
                  value: campaign.target_markets.length ? campaign.target_markets.map((m) => `${m.display_name} (${m.country_code})`).join(", ") : "None set",
                  muted: !campaign.target_markets.length,
                },
                { label: "Languages", value: notYet, muted: true },
                { label: "Channels", value: notYet, muted: true },
                { label: "Budget", value: notYet, muted: true },
                { label: "Campaign dates", value: notYet, muted: true },
                { label: "Success metric", value: notYet, muted: true },
                { label: "Created", value: formatDateTime(campaign.created_at) },
              ]}
            />
            <div className="mt-7">
              <SectionTitle meta="Weights must total 1.000; never rescaled">Scoring weights</SectionTitle>
            </div>
            <LedgerList
              rows={WEIGHT_FIELDS.map((f) => ({
                label: f.label,
                value: (
                  <span className="type-ledger tabular-nums">
                    {campaign.evaluation_criteria[f.key].toFixed(2)} <span className="text-ink-muted">· {f.help}</span>
                  </span>
                ),
              }))}
            />
          </section>
          <section aria-labelledby="creative">
            <SectionTitle id="creative" meta={`v${campaign.current_version.version_number} · saved ${formatDateTime(campaign.current_version.created_at)}`}>
              Original creative, current version
            </SectionTitle>
            <CreativeMat content={content} />
            {content.reference_terms.length > 0 && (
              <div className="mt-3 space-y-1.5">
                <p className="type-meta">Cultural references in the copy</p>
                <Terms terms={content.reference_terms} empty="" />
              </div>
            )}
          </section>
        </div>
      )}
      <BrandKitPanel />
    </>
  );
}
