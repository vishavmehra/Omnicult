"use client";

import { BookMarked, Bot, Crop, GitCompareArrows, History, Languages, Layers, ScanSearch, ShieldAlert, Sparkles, SpellCheck, User, Wand2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/use-media-query";
import { DirectPanel } from "@/features/direct/direct-panel";
import { useCreateVersion, useLocks, useOperations, useRegions, useRestoreVersion, useVersion, useVersions } from "@/features/studio/api";
import { DiffView } from "@/features/studio/diff";
import { ElementEditor } from "@/features/studio/elements";
import { GlossaryPanel } from "@/features/studio/glossary";
import { formatCost, dialWord, lineage, numberVersions, OPERATION_LABEL, originalOf, pairElements, placeTag, TONE_DIALS } from "@/features/studio/model";
import { MutationError, StudioProvider, useStudio, type StudioContextValue } from "@/features/studio/parts";
import { TranscreatePanel } from "@/features/studio/transcreate";
import type { Operation, RegionLanguage, VersionNode, VersionSummary } from "@/features/studio/types";
import { VersionTree } from "@/features/studio/version-tree";
import { ClaimGuardPanel } from "@/features/studio-t3/claim-guard";
import { FormatFitPanel } from "@/features/studio-t3/format-fit";
import { ScriptCheckPanel } from "@/features/studio-t3/script-check";
import { formatDateTime, shownModel } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { WorkspaceHeader } from "./parts";

type TabKey = "elements" | "transcreate" | "direct" | "compare" | "glossary" | "format" | "claims" | "script";
const TABS: readonly TabKey[] = ["elements", "transcreate", "direct", "compare", "glossary", "format", "claims", "script"];
const asTab = (value: string | null): TabKey => (TABS as readonly string[]).includes(value ?? "") ? (value as TabKey) : "elements";

/** One link into Creative X-Ray, the other half of the Studio (another stream builds that page). */
function XRayLink({ campaignId, className }: { campaignId: string; className?: string }) {
  return (
    <Link href={`/app/c/${campaignId}/studio/xray`} className={cn(buttonVariants({ variant: "outline" }), className)}>
      <ScanSearch aria-hidden />
      Creative X-Ray
    </Link>
  );
}

/** One link into Generate, where new images, voice-overs and jingles are made from the brief and Brand Kit. */
function GenerateLink({ campaignId, className }: { campaignId: string; className?: string }) {
  return (
    <Link href={`/app/c/${campaignId}/studio/generate`} className={cn(buttonVariants({ variant: "outline" }), className)}>
      <Sparkles aria-hidden />
      Generate
    </Link>
  );
}

/** The selected version: what it is, who or what made it and why, what the AI part cost, the tone it carries, and restore. */
function VersionHeader({
  version,
  number,
  op,
  isNewest,
  onOpenVersion,
}: {
  version: VersionNode;
  number: number;
  op: Operation | undefined;
  isNewest: boolean;
  onOpenVersion(id: string): void;
}) {
  const { campaignId } = useStudio();
  const restore = useRestoreVersion(campaignId);
  const place = placeTag(version);
  const tone = version.settings.tone;
  const gen = version.settings.generation;
  const model = gen && typeof gen.model_id === "string" ? shownModel(gen.model_id) : null;
  const prompt = gen && typeof gen.prompt_version === "string" ? gen.prompt_version : null;
  const cost = version.actor === "ai" ? formatCost(op?.estimated_cost_usd) : null;
  return (
    <section aria-labelledby="version-title" className="space-y-3 rounded-card border border-border bg-surface px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 space-y-1">
          <h2 id="version-title" className="text-[16px] font-semibold text-ink">
            <span className="mr-2 font-mono text-[13px] font-normal text-ink-muted">v{number}</span>
            {version.label}
          </h2>
          <p className="type-ledger flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-secondary">
            <span className="inline-flex items-center gap-1">
              {version.actor === "ai" ? <Bot aria-hidden className="size-3.5" /> : <User aria-hidden className="size-3.5" />}
              {version.actor === "ai" ? "AI proposal, applied by a person" : "Made by a person"}
            </span>
            <span>{op ? OPERATION_LABEL[op.kind] : "Original, imported"}</span>
            {place && <span className="font-mono text-[11.5px]">{place}</span>}
            <span>{formatDateTime(version.created_at)}</span>
            {cost && <span>{cost} (estimate)</span>}
          </p>
        </div>
        <Button
          variant="outline"
          disabled={isNewest || restore.isPending}
          title={isNewest ? "This is already the newest version." : "Make a new version that copies this one."}
          onClick={() => restore.mutate({ versionId: version.id }, { onSuccess: (r) => { toast.success("Restored as a new version"); onOpenVersion(r.version.id); } })}
        >
          <History aria-hidden />
          {restore.isPending ? "Restoring…" : "Restore as a new version"}
        </Button>
      </div>
      {op && <p className="max-w-[68ch] text-[13.5px] text-ink-body">{op.reason}</p>}
      {(model || prompt) && (
        <p className="type-meta">
          {model && <>Model {model}</>}
          {model && prompt && " · "}
          {prompt && <>prompt {prompt}</>}
        </p>
      )}
      {tone && (
        <dl aria-label="Tone dials of this version" className="type-ledger flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
          {TONE_DIALS.map((d) => (
            <div key={d.key} className="flex gap-1.5">
              <dt className="text-ink-muted">{d.label}</dt>
              <dd className="text-ink-body">{dialWord(d, tone[d.key])}</dd>
            </div>
          ))}
        </dl>
      )}
      {restore.isError && <MutationError error={restore.error} />}
    </section>
  );
}

/** What the version tree panel needs to say before there is a tree. */
function TreePanel({
  state,
  versions,
  total,
  operations,
  selectedId,
  newestId,
  onSelect,
}: {
  state: "loading" | "error" | "ready";
  versions: VersionSummary[];
  total: number;
  operations: Operation[];
  selectedId: string | null;
  newestId: string | null;
  onSelect(id: string): void;
}) {
  if (state === "loading") return <LoadingState label="Loading the version tree…" />;
  if (state === "error") return <p className="text-[13px] text-danger">The version tree could not be loaded.</p>;
  if (versions.length === 0) return <p className="text-[13px] text-ink-muted">No versions yet. The first one is the original you import.</p>;
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        Every change makes a new version. The original is never overwritten. Two regions made from the same version appear as branches.
      </p>
      <VersionTree versions={versions} total={total} operations={operations} selectedId={selectedId ?? ""} newestId={newestId} onSelect={onSelect} />
    </div>
  );
}

/**
 * Creative Studio: the version tree, an element editor with the original beside the adapted copy, locks, Tweak Chips,
 * Transcreate with tone dials and per-line checks, a diff between any two versions, and the Brand Glossary. Every change
 * makes a new version (the original is never overwritten) and a locked element refuses every change, from people and from AI.
 */
export function StudioWorkspace() {
  const { campaign, project } = useCampaign();
  const campaignId = campaign.id;
  const docked = useMediaQuery("(min-width: 1280px)");
  const versionsQ = useVersions(campaignId);
  const operationsQ = useOperations(campaignId);
  const locksQ = useLocks(campaignId);
  const regionsQ = useRegions();
  const create = useCreateVersion(campaignId);
  // The tab and the selected version are kept in the address (?tab=…&v=…), so a refresh or a shared link lands on the same view.
  const params = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(() => params.get("v"));
  const [tab, setTab] = useState<TabKey>(() => asTab(params.get("tab")));
  // Lives here, not in the Transcreate tab, so a run in progress survives switching tabs or versions.
  const [runId, setRunId] = useState<string | null>(null);

  const versions = useMemo(() => versionsQ.data?.items ?? [], [versionsQ.data]);
  const operations = useMemo(() => operationsQ.data?.items ?? [], [operationsQ.data]);
  const numbers = useMemo(() => numberVersions(versions), [versions]);
  const newest = useMemo(() => [...versions].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)).at(-1) ?? null, [versions]);
  const current = versions.find((v) => v.id === selectedId) ?? newest;
  const chain = useMemo(() => (current ? lineage(versions, current.id) : []), [versions, current]);
  const original = current ? originalOf(versions, current.id) : null;
  const isOriginal = Boolean(current && current.parent_id === null);

  const node = useVersion(campaignId, current?.id ?? null);
  const originalNode = useVersion(campaignId, original && !isOriginal ? original.id : null);

  const languages = useMemo(() => {
    const seen = new Map<string, RegionLanguage>();
    for (const r of regionsQ.data?.items ?? []) for (const l of r.languages) if (!seen.has(l.code)) seen.set(l.code, l);
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [regionsQ.data]);
  const ctx: StudioContextValue = useMemo(
    () => ({ campaignId, projectId: project.id, workspaceId: project.workspace_id, demo: project.mode === "demo", languageNames: new Map(languages.map((l) => [l.code, l.name])), languages }),
    [campaignId, project.id, project.workspace_id, project.mode, languages],
  );

  // The Command Bar's "Direct this version" asks an already open Studio for a tab with an event; from any other page it
  // arrives as ?tab=direct and the state above reads it on mount.
  useEffect(() => {
    const onTab = (e: Event) => setTab(asTab((e as CustomEvent<string>).detail));
    window.addEventListener("omnicult:studio-tab", onTab);
    return () => window.removeEventListener("omnicult:studio-tab", onTab);
  }, []);

  const currentId = current?.id ?? null;
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    q.set("tab", tab);
    if (currentId) q.set("v", currentId);
    window.history.replaceState(window.history.state, "", `${window.location.pathname}?${q}`);
  }, [tab, currentId]);

  function open(id: string) {
    setSelectedId(id);
    setTab("elements");
  }

  const treeState = versionsQ.isPending ? "loading" : versionsQ.isError ? "error" : "ready";
  const tree = (
    <TreePanel
      state={treeState}
      versions={versions}
      total={versionsQ.data?.total ?? 0}
      operations={operations}
      selectedId={current?.id ?? null}
      newestId={newest?.id ?? null}
      onSelect={(id) => setSelectedId(id)}
    />
  );
  const regions = campaign.target_markets.map((m) => m.display_name);
  const hasCopy = Boolean(campaign.current_version.content.headline || campaign.current_version.content.body || campaign.current_version.content.call_to_action);

  return (
    <StudioProvider value={ctx}>
      <WorkspaceHeader workspace="studio" actions={<><XRayLink campaignId={campaignId} /><GenerateLink campaignId={campaignId} /></>}>
        <p className="type-ledger flex flex-wrap gap-x-4 gap-y-1 pt-1 text-[12.5px] text-ink-muted">
          <span>
            <span className="text-ink-body">{campaign.name}</span> · {project.brand.name}
          </span>
          <span>{regions.length ? `Brief regions: ${regions.join(", ")}` : "No target regions in the brief"}</span>
          {versionsQ.data && (
            <span>
              {versionsQ.data.total} {versionsQ.data.total === 1 ? "version" : "versions"} · {locksQ.data?.total ?? 0} locked
            </span>
          )}
        </p>
      </WorkspaceHeader>

      {!docked && (
        <details className="mb-5 rounded-card border border-border bg-surface px-4 py-3">
          <summary className="cursor-pointer text-[14px] font-semibold text-ink select-none">
            Version tree
            <span className="ml-2 font-normal text-ink-muted">{current ? `v${numbers.get(current.id)} selected` : ""}</span>
          </summary>
          <div className="mt-3">{tree}</div>
        </details>
      )}
      {docked && <ContextPanel title="Version tree">{tree}</ContextPanel>}

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <div className="flex flex-wrap items-center gap-x-4 border-b border-border">
          <TabsList variant="line" className="h-auto max-w-full flex-wrap justify-start gap-y-1 group-data-horizontal/tabs:h-auto">
            <TabsTrigger value="elements" className="h-9 flex-none px-3">
              <Layers aria-hidden />
              Elements
            </TabsTrigger>
            <TabsTrigger value="transcreate" className="h-9 flex-none px-3">
              <Languages aria-hidden />
              Transcreate
            </TabsTrigger>
            <TabsTrigger value="direct" className="h-9 flex-none px-3">
              <Wand2 aria-hidden />
              Direct
            </TabsTrigger>
            <TabsTrigger value="compare" className="h-9 flex-none px-3">
              <GitCompareArrows aria-hidden />
              Compare versions
            </TabsTrigger>
            <TabsTrigger value="glossary" className="h-9 flex-none px-3">
              <BookMarked aria-hidden />
              Brand Glossary
            </TabsTrigger>
            <TabsTrigger value="format" className="h-9 flex-none px-3">
              <Crop aria-hidden />
              Format Fit
            </TabsTrigger>
            <TabsTrigger value="claims" className="h-9 flex-none px-3">
              <ShieldAlert aria-hidden />
              Claim Guard
            </TabsTrigger>
            <TabsTrigger value="script" className="h-9 flex-none px-3">
              <SpellCheck aria-hidden />
              Script Check
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="pt-5">
          {tab !== "glossary" && versionsQ.isError && <ErrorState error={versionsQ.error} onRetry={() => void versionsQ.refetch()} />}
          {tab !== "glossary" && versionsQ.isPending && <LoadingState label="Loading the version tree…" />}
          {tab !== "glossary" && versionsQ.data && versions.length === 0 && (
            <div className="space-y-3">
              <EmptyState
                title="No versions yet"
                description={
                  <>
                    A version is one saved state of the creative. Start by importing the original: the headline, body and call to action of this campaign become version 1. After that every edit, tweak chip, transcreation or restore makes a new version beside it, and the original is never overwritten.
                  </>
                }
                needs={[
                  { label: "Campaign copy to import (headline, body or call to action)", met: hasCopy },
                  { label: "An original version in the tree", met: false },
                ]}
                action={
                  <div className="flex flex-wrap items-center gap-3">
                    <Button size="lg" disabled={!hasCopy || create.isPending} onClick={() => create.mutate({ label: "Original", language: "en" }, { onSuccess: () => toast.success("Original imported as version 1") })}>
                      {create.isPending ? "Importing…" : "Start from the campaign copy"}
                    </Button>
                    <span className="text-[13px] text-ink-muted">or decompose an uploaded video, image or audio creative first:</span>
                    <XRayLink campaignId={campaignId} />
                  </div>
                }
              />
              {create.isError && <MutationError error={create.error} />}
            </div>
          )}

          {current && (
            <>
              <TabsContent value="elements" className="space-y-5">
                {node.isPending ? (
                  <LoadingState label="Loading the version…" />
                ) : node.isError ? (
                  <ErrorState error={node.error} onRetry={() => void node.refetch()} />
                ) : (
                  <>
                    <VersionHeader version={node.data} number={numbers.get(current.id) ?? 0} op={operations.find((o) => o.id === current.operation_id)} isNewest={current.id === newest?.id} onOpenVersion={open} />
                    {!isOriginal && originalNode.isPending ? (
                      <LoadingState label="Loading the original to set beside it…" />
                    ) : (
                      <ElementEditor
                        pairs={pairElements(isOriginal ? null : (originalNode.data ?? null), node.data)}
                        version={node.data}
                        isOriginal={isOriginal}
                        locks={locksQ.data?.items ?? []}
                        operations={operations}
                        chain={chain}
                        onOpenVersion={open}
                      />
                    )}
                    {originalNode.isError && <ErrorState error={originalNode.error} onRetry={() => void originalNode.refetch()} />}
                    {locksQ.isError && <ErrorState error={locksQ.error} onRetry={() => void locksQ.refetch()} />}
                  </>
                )}
              </TabsContent>
              <TabsContent value="transcreate">
                {node.data ? (
                  <TranscreatePanel version={node.data} locks={locksQ.data?.items ?? []} operations={operations} runId={runId} onRun={setRunId} onOpenVersion={open} />
                ) : node.isError ? (
                  <ErrorState error={node.error} onRetry={() => void node.refetch()} />
                ) : (
                  <LoadingState label="Loading the version…" />
                )}
              </TabsContent>
              <TabsContent value="direct">
                {node.data ? (
                  <DirectPanel
                    key={current.id}
                    version={node.data}
                    number={numbers.get(current.id) ?? 0}
                    numbers={numbers}
                    onOpenVersion={open}
                    onShowRun={(id) => {
                      setRunId(id);
                      setTab("transcreate");
                    }}
                  />
                ) : node.isError ? (
                  <ErrorState error={node.error} onRetry={() => void node.refetch()} />
                ) : (
                  <LoadingState label="Loading the version…" />
                )}
              </TabsContent>
              <TabsContent value="compare">
                <DiffView key={current.id} versions={versions} numbers={numbers} selectedId={current.id} />
              </TabsContent>
              {/* Tier 3: these read the selected version; each fetches only while its tab is open. */}
              <TabsContent value="format" className="space-y-4">
                {node.data ? <FormatFitPanel campaignId={campaignId} version={node.data} /> : node.isError ? <ErrorState error={node.error} onRetry={() => void node.refetch()} /> : <LoadingState label="Loading the version…" />}
              </TabsContent>
              <TabsContent value="claims" className="space-y-4">
                {node.data ? <ClaimGuardPanel key={current.id} campaignId={campaignId} version={node.data} demo={project.mode === "demo"} /> : node.isError ? <ErrorState error={node.error} onRetry={() => void node.refetch()} /> : <LoadingState label="Loading the version…" />}
              </TabsContent>
              <TabsContent value="script" className="space-y-4">
                <ScriptCheckPanel key={current.id} campaignId={campaignId} versionId={current.id} />
              </TabsContent>
            </>
          )}
          <TabsContent value="glossary">
            <GlossaryPanel />
          </TabsContent>
        </div>
      </Tabs>
    </StudioProvider>
  );
}
