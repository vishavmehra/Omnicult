"use client";

import { ArrowLeft, ImageIcon, Mic, Music2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState, type ComponentType } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { useRegions } from "@/features/desk/api";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { cn } from "@/lib/utils";

import {
  useBriefRegions,
  useGenerateCapabilities,
  useGenerateItems,
  useGenerateRun,
  useProjectImages,
  type GenerateKind,
} from "./api";
import { Gallery } from "./gallery";
import "./generate.css";
import { ImageForm, type ReferenceOption } from "./image-form";
import { JingleForm } from "./jingle-form";
import { Notice, RunError, usd } from "./parts";
import { EmptyStage, ItemView, WorkingStage } from "./stage";
import { VoiceForm } from "./voice-form";

const ICON: Record<GenerateKind, ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = { image: ImageIcon, voice: Mic, jingle: Music2 };
const WORD: Record<GenerateKind, string> = { image: "image", voice: "voice-over", jingle: "jingle" };
const BLURB: Record<GenerateKind, string> = {
  image: "A key visual or social post, with your logo, product and headline placed in code",
  voice: "Lines spoken in a regional language, joined into one track with timings",
  jingle: "A short instrumental from Lyria, cut to the length you pick",
};

/** Generate: new images, voice-overs and jingles from the campaign's brief and Brand Kit, each kept with how it was made. */
export function GenerateWorkspace() {
  const { campaign, project } = useCampaign();
  const caps = useGenerateCapabilities(campaign.id);
  const items = useGenerateItems(campaign.id);
  const regions = useRegions();
  const briefRegions = useBriefRegions(campaign.id);
  const uploads = useProjectImages(project.id);
  const [pick, setPick] = useState<GenerateKind | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [runKind, setRunKind] = useState<GenerateKind>("image");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const run = useGenerateRun(campaign.id, runId);
  const stageRef = useRef<HTMLElement>(null);

  const available = useMemo(() => caps.data?.generators.filter((g) => g.available) ?? [], [caps.data]);
  const kind: GenerateKind = (available.find((g) => g.kind === pick) ?? available[0])?.kind ?? "image";

  const references = useMemo<ReferenceOption[]>(() => {
    const out = new Map<string, ReferenceOption>();
    for (const p of caps.data?.brand.products ?? []) {
      if (p.asset_id && p.url) out.set(p.asset_id, { id: p.asset_id, label: p.label, source: "Brand Kit product image", kit: true, asset: { asset_id: p.asset_id, url: p.url } });
    }
    for (const i of items.data ?? []) {
      if (i.kind === "image" && i.asset && i.status !== "failed") out.set(i.asset.asset_id, { id: i.asset.asset_id, label: i.title, source: "generated here", asset: i.asset });
    }
    // a Brand Kit product image is also an upload of the project: keep its Brand Kit entry (and its flag) rather than the plain upload
    for (const a of uploads.data ?? []) if (!out.has(a.id)) out.set(a.id, { id: a.id, label: a.filename, source: "uploaded", asset: { asset_id: a.id, url: a.content_url } });
    return [...out.values()];
  }, [caps.data, items.data, uploads.data]);

  const error = caps.error ?? items.error ?? regions.error ?? briefRegions.error;
  if (error) {
    return <Shell campaignId={campaign.id}><ErrorState error={error} onRetry={() => { void caps.refetch(); void items.refetch(); void regions.refetch(); void briefRegions.refetch(); }} /></Shell>;
  }
  if (!caps.data || !items.data || !regions.data || !briefRegions.data) {
    return <Shell campaignId={campaign.id}><LoadingState label="Opening Generate…" /></Shell>;
  }

  const data = caps.data;
  const list = items.data;
  const startRegion = briefRegions.data.find((c) => regions.data.some((r) => r.code === c)) ?? regions.data[0]?.code ?? "IN-MH";
  const runStatus = run.data?.status;
  const running = Boolean(runId) && (!runStatus || runStatus === "queued" || runStatus === "running");
  const runItem = runId ? list.find((i) => i.id === runId) : undefined;
  const selected = (selectedId ? list.find((i) => i.id === selectedId) : undefined) ?? runItem;
  const settling = Boolean(runId) && !running && !runItem && (runStatus === "completed" || runStatus === "partial");
  const failedRun = Boolean(runId) && (runStatus === "failed" || runStatus === "cancelled" || runItem?.status === "failed");
  // One short sentence for screen readers, set only when a run starts, finishes or fails: nothing in the result is a live region.
  const announcement = running || settling ? `Making your ${WORD[runKind]}` : failedRun ? "This run did not finish" : runItem && selected?.id === runItem.id ? `Your ${WORD[runKind]} is ready` : "";

  function started(id: string, forKind: GenerateKind) {
    setRunId(id);
    setRunKind(forKind);
    setSelectedId(null);
    stageRef.current?.scrollTo({ top: 0 });
    // On a phone the result sits below the controls: bring it into view. On a wide screen it is already beside them.
    window.setTimeout(() => {
      const box = stageRef.current?.getBoundingClientRect();
      if (box && (box.top < 0 || box.top > window.innerHeight * 0.7)) {
        stageRef.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      }
    }, 60);
  }

  const stage = running || settling ? (
    <WorkingStage kind={runKind} run={run.data} />
  ) : selected ? (
    <ItemView key={selected.id} campaignId={campaign.id} item={selected} onReference={(id) => { setReference(id); setPick("image"); }} />
  ) : runId && (runStatus === "failed" || runStatus === "cancelled") ? (
    <RunError error={run.data?.error} />
  ) : (
    <EmptyStage kind={kind} />
  );

  return (
    <Shell campaignId={campaign.id}>
      {available.length === 0 ? (
        <Notice>No generator can run here yet: the server has no image, speech or music model configured. Use a demo project, or configure Google (Vertex AI).</Notice>
      ) : (
        <div className="grid gap-5 lg:h-[calc(100dvh-8rem)] lg:min-h-[32rem] lg:grid-cols-[minmax(0,27rem)_minmax(0,1fr)] xl:gap-7">
          <section aria-label="Set up a generator" className="min-w-0 space-y-4 rounded-card border border-border bg-surface p-4 shadow-raised sm:p-5 lg:h-full lg:overflow-y-auto lg:overscroll-contain">
            <div
              role="tablist"
              aria-label="Generator"
              className="grid grid-cols-3 gap-1.5 rounded-xl bg-surface-muted p-1 shadow-well"
              onKeyDown={(e) => {
                const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                e.preventDefault();
                const next = available[(available.findIndex((g) => g.kind === kind) + step + available.length) % available.length];
                setPick(next.kind);
                document.getElementById(`gen-tab-${next.kind}`)?.focus();
              }}
            >
              {available.map((g) => {
                const Icon = ICON[g.kind];
                return (
                  <button
                    key={g.kind}
                    type="button"
                    role="tab"
                    id={`gen-tab-${g.kind}`}
                    aria-selected={kind === g.kind}
                    aria-controls={`gen-panel-${g.kind}`}
                    tabIndex={kind === g.kind ? 0 : -1}
                    onClick={() => setPick(g.kind)}
                    className={cn(
                      "flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-lg px-2 py-1.5 text-[13.5px] font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                      kind === g.kind ? "bg-surface-raised text-ink shadow-raised" : "text-ink-secondary hover:text-ink",
                    )}
                  >
                    <Icon aria-hidden className={cn("size-5", kind === g.kind && "text-primary")} />
                    {g.label}
                  </button>
                );
              })}
            </div>
            <p className="text-[13.5px] text-ink-secondary">{BLURB[kind]}.{data.mode === "live" && available.find((g) => g.kind === kind)?.estimated_cost_usd != null ? ` About ${usd(available.find((g) => g.kind === kind)?.estimated_cost_usd)} ${kind === "voice" ? "a line" : "a run"}.` : ""}</p>
            {available.map((g) => (
              <div key={g.kind} role="tabpanel" id={`gen-panel-${g.kind}`} aria-labelledby={`gen-tab-${g.kind}`} hidden={kind !== g.kind}>
                {g.kind === "image" && (
                  <ImageForm
                    campaignId={campaign.id}
                    caps={data}
                    regions={regions.data}
                    startRegion={startRegion}
                    references={references}
                    reference={reference}
                    onReference={setReference}
                    working={running}
                    onStarted={(id) => started(id, "image")}
                  />
                )}
                {g.kind === "voice" && (
                  <VoiceForm campaignId={campaign.id} caps={data} regions={regions.data} startRegion={startRegion} working={running} onStarted={(id) => started(id, "voice")} />
                )}
                {g.kind === "jingle" && (
                  <JingleForm campaignId={campaign.id} caps={data} regions={regions.data} startRegion={startRegion} working={running} onStarted={(id) => started(id, "jingle")} />
                )}
              </div>
            ))}
          </section>

          <section
            ref={stageRef}
            aria-label="Result"
            className="min-w-0 scroll-mt-20 space-y-4 [overflow-anchor:none] lg:h-full lg:overflow-y-auto lg:overscroll-contain lg:pr-1"
          >
            <p role="status" className="sr-only">
              {announcement}
            </p>
            {stage}
          </section>
        </div>
      )}
      {available.length > 0 && <Gallery
          items={list}
          selectedId={selected?.id ?? null}
          onSelect={(id) => {
            setSelectedId(id);
            stageRef.current?.scrollTo({ top: 0 });
            const top = stageRef.current ? stageRef.current.getBoundingClientRect().top : 0;
            if (top < 0 || top > window.innerHeight * 0.7) {
              window.scrollTo({ top: window.scrollY + top - 90, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
            }
          }}
        />}
    </Shell>
  );
}

function Shell({ campaignId, children }: { campaignId: string; children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-4">
        <div className="min-w-0 space-y-1">
          <Link href={`/app/c/${campaignId}/studio`} className="inline-flex items-center gap-1 text-[12.5px] text-ink-secondary hover:text-ink">
            <ArrowLeft aria-hidden className="size-3.5" />
            Creative Studio
          </Link>
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Generate</h1>
          <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
            New images, voice-overs and jingles from this campaign&apos;s brief and Brand Kit, each stored with how it was made.
          </p>
        </div>
      </header>
      {children}
    </div>
  );
}
