"use client";

import { ArrowUpRight, History, PencilLine } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { workspaceHref } from "@/components/shell/workspaces";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBrief, useBriefVersion, useBriefVersions, useRegions, useToday } from "@/features/desk/api";
import { BrandKitTab } from "@/features/desk/brand-kit";
import { BriefEditor } from "@/features/desk/brief-editor";
import { BriefDocument, VersionBar } from "@/features/desk/brief-view";
import { CommandBarButton } from "@/features/desk/command-bar";
import { CopyEditor } from "@/features/desk/copy-editor";
import type { BriefContent } from "@/features/desk/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, CreativeMat, LedgerList, SectionTitle, WorkspaceHeader } from "./parts";
import { WEIGHT_FIELDS } from "@/features/project/campaign-form";

type TabKey = "brief" | "brand-kit" | "creative";
const TABS: { key: TabKey; label: string }[] = [
  { key: "brief", label: "Campaign brief" },
  { key: "brand-kit", label: "Brand Kit" },
  { key: "creative", label: "Original creative" },
];
const isTab = (v: string | null): v is TabKey => TABS.some((t) => t.key === v);

/** This campaign's next actions and readiness, from the same API as Today, narrowed to one campaign. */
function NextForCampaign({ campaignId }: { campaignId: string }) {
  const q = useToday(campaignId);
  const card = q.data?.campaigns[0];
  return (
    <section aria-labelledby="next-for-campaign" className="space-y-2.5">
      <h3 id="next-for-campaign" className="text-[13px] font-semibold text-ink">
        Next for this campaign
      </h3>
      {q.isPending ? (
        <LoadingState label="Checking the campaign…" className="py-2" />
      ) : q.error ? (
        <p className="text-[12.5px] text-danger">Could not read the campaign state.</p>
      ) : !card || card.next_actions.length === 0 ? (
        <p className="text-[12.5px] text-ink-secondary">Nothing is waiting: the brief is complete and no run, verdict or conflict needs you.</p>
      ) : (
        <ol className="ledger-rules rounded-card border border-border bg-surface">
          {card.next_actions.slice(0, 4).map((a) => (
            <li key={a.id}>
              <Link href={workspaceHref(campaignId, a.workspace)} className="group flex items-start gap-2 px-3 py-2.5 hover:bg-surface-muted focus-visible:-outline-offset-2">
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-ink">{a.title}</span>
                  <span className="block text-[12px] text-ink-secondary">{a.reason}</span>
                </span>
                <ArrowUpRight aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted group-hover:text-rose" />
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function BriefHistory({ campaignId, viewing, onView }: { campaignId: string; viewing: number | null; onView(version: number | null): void }) {
  const q = useBriefVersions(campaignId);
  return (
    <section aria-labelledby="brief-history" className="space-y-2.5">
      <h3 id="brief-history" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink">
        <History aria-hidden className="size-3.5 text-ink-muted" />
        Brief history
      </h3>
      {q.isPending ? (
        <LoadingState label="Loading versions…" className="py-2" />
      ) : q.error ? (
        <p className="text-[12.5px] text-danger">Could not load the versions.</p>
      ) : q.data.length === 0 ? (
        <p className="text-[12.5px] text-ink-secondary">No version saved yet. The first save becomes version 1.</p>
      ) : (
        <ol className="ledger-rules rounded-card border border-border bg-surface">
          {q.data.map((v, i) => {
            const current = i === 0;
            const active = viewing === null ? current : viewing === v.version;
            return (
              <li key={v.version}>
                <button
                  type="button"
                  onClick={() => onView(current ? null : v.version)}
                  aria-current={active ? "true" : undefined}
                  className={cn("block w-full px-3 py-2.5 text-left hover:bg-surface-muted focus-visible:-outline-offset-2", active && "bg-surface-raised")}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="type-ledger text-[13px] font-medium text-ink">
                      Version {v.version}
                      {current && <span className="type-meta ml-1.5">current</span>}
                    </span>
                    <span className="type-meta" title={formatDateTime(v.created_at)}>
                      {formatRelative(v.created_at)}
                    </span>
                  </span>
                  {v.change_note && <span className="block text-[12px] text-ink-body">{v.change_note}</span>}
                  <span className="block truncate text-[11.5px] text-ink-muted">
                    {v.provenance.source === "demo_fixture" ? "Demonstration fixture · " : ""}
                    Changed: {v.changed_fields.join(", ") || "nothing"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** Campaign Desk for one campaign: the brief every other workspace reads, the Brand Kit, and the original creative. */
export function DeskWorkspace() {
  const { campaign, project } = useCampaign();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab: TabKey = isTab(params.get("tab")) ? (params.get("tab") as TabKey) : "brief";
  const demo = project.mode === "demo";

  const briefQ = useBrief(campaign.id);
  const regionsQ = useRegions();
  const [viewing, setViewing] = useState<number | null>(null);
  const older = useBriefVersion(campaign.id, viewing);
  const [editingBrief, setEditingBrief] = useState(params.get("edit") === "brief");
  const [editFrom, setEditFrom] = useState<BriefContent | null>(null);
  const [editingCopy, setEditingCopy] = useState(false);

  const brief = briefQ.data;
  const setTab = (next: TabKey) => router.replace(next === "brief" ? pathname : `${pathname}?tab=${next}`, { scroll: false });
  const content = campaign.current_version.content;
  const canEditBrief = Boolean(brief?.editable);

  return (
    <>
      <WorkspaceHeader
        workspace="desk"
        actions={
          <>
            <CommandBarButton />
            {tab === "brief" && canEditBrief && !editingBrief && viewing === null && (
              <Button onClick={() => { setEditFrom(null); setEditingBrief(true); }}>
                <PencilLine aria-hidden />
                {brief?.saved ? "Edit brief" : "Write the brief"}
              </Button>
            )}
          </>
        }
      >
        <CampaignFacts />
      </WorkspaceHeader>

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <TabsList variant="line" className="h-10 max-w-full justify-start overflow-x-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t.key} value={t.key} className="h-9 flex-none px-3">
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="brief" className="space-y-5 pt-4">
          {briefQ.isPending || regionsQ.isPending ? (
            <LoadingState label="Opening the brief…" />
          ) : briefQ.error || regionsQ.error || !brief ? (
            <ErrorState error={briefQ.error ?? regionsQ.error} onRetry={() => { void briefQ.refetch(); void regionsQ.refetch(); }} />
          ) : editingBrief && canEditBrief ? (
            <BriefEditor
              brief={brief}
              initial={editFrom ?? brief.content}
              regions={regionsQ.data!}
              onCancel={() => { setEditingBrief(false); setEditFrom(null); }}
              onSaved={() => { setEditingBrief(false); setEditFrom(null); setViewing(null); }}
            />
          ) : (
            <>
              <VersionBar brief={brief} viewing={viewing !== null && older.data ? { version: older.data.version, createdAt: older.data.created_at, note: older.data.change_note } : undefined} />
              <p className="max-w-[72ch] text-[12.5px] text-ink-secondary">
                Saving the brief writes its objective and target regions to the campaign record, which Proof Vault and the evidence graph read. The rest is kept in this versioned brief for every workspace to read.
              </p>
              {!brief.editable && brief.locked_reason && (
                <p className="max-w-[72ch] text-[12.5px] text-ink-muted">{brief.locked_reason}</p>
              )}
              {viewing !== null && (
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={() => setViewing(null)}>
                    Back to the current version
                  </Button>
                  {canEditBrief && older.data && (
                    <Button variant="outline" size="sm" onClick={() => { setEditFrom(older.data.content); setEditingBrief(true); setViewing(null); }}>
                      Edit from version {older.data.version}
                    </Button>
                  )}
                </div>
              )}
              {viewing !== null && older.isPending ? (
                <LoadingState label={`Loading version ${viewing}…`} />
              ) : viewing !== null && older.error ? (
                <ErrorState error={older.error} onRetry={() => void older.refetch()} />
              ) : (
                <BriefDocument content={viewing !== null && older.data ? older.data.content : brief.content} regions={regionsQ.data} sample={demo} />
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="brand-kit" className="pt-4">
          <BrandKitTab projectId={campaign.project_id} campaignId={campaign.id} />
        </TabsContent>

        <TabsContent value="creative" className="space-y-6 pt-4">
          {editingCopy ? (
            <CopyEditor campaign={campaign} demo={demo} onCancel={() => setEditingCopy(false)} onDone={() => setEditingCopy(false)} />
          ) : (
            <div className="grid gap-8 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
              <section aria-labelledby="creative">
                <SectionTitle id="creative" meta={`v${campaign.current_version.version_number} · saved ${formatDateTime(campaign.current_version.created_at)}`}>
                  Original creative, current version
                </SectionTitle>
                <CreativeMat content={content} />
                {content.reference_terms.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <p className="type-meta">Cultural references in the copy</p>
                    <ul className="flex flex-wrap gap-1.5">
                      {content.reference_terms.map((t) => (
                        <li key={t} className="rounded-stamp border border-border-strong/45 bg-surface-raised px-1.5 py-0.5 text-[12.5px] text-ink">
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
              <section aria-labelledby="weights">
                <SectionTitle id="weights" meta="Weights must total 1.000; never rescaled">
                  Scoring weights
                </SectionTitle>
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
                <div className="mt-4">
                  <Button variant="outline" onClick={() => setEditingCopy(true)}>
                    <PencilLine aria-hidden />
                    Edit copy and weights
                  </Button>
                </div>
              </section>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <ContextPanel title="Campaign state">
        <NextForCampaign campaignId={campaign.id} />
        <BriefHistory campaignId={campaign.id} viewing={viewing} onView={(v) => { setViewing(v); if (v !== null) setTab("brief"); }} />
      </ContextPanel>
    </>
  );
}
