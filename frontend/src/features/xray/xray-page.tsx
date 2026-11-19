"use client";

import { ArrowLeft, Play, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { CampaignFacts, SectionTitle } from "@/features/workspaces/parts";
import { UseXRayLayoutButton } from "@/features/studio/start-version";
import { useRun } from "@/lib/api/runs";

import { AnalysisPanel } from "./analysis";
import { isActive, useCreative, useCreatives, useScenes, useStartXRay, useUploads, type Asset, type Creative } from "./api";
import { CreativePicker } from "./creative-picker";
import { FrameStage, type StageBox } from "./frame-stage";
import { plural } from "./media-file";
import { clock, ProvenanceTag } from "./parts";
import { Player } from "./player";
import { SceneDetail, SceneStrip } from "./scenes";
import { TextPreviewTool } from "./text-preview";
import { RunForm, UploadForm, KIND_LABEL } from "./upload-panel";

const ROLE_LABEL: Record<string, string> = {
  headline: "Headline", body: "Body", cta: "Call to action", tagline: "Tagline", caption: "Caption", logo: "Logo", product: "Product", packshot: "Pack",
};
const KEPT_ROLES = new Set(["logo", "product", "packshot", "tagline"]); // the never-change kinds Remake keeps as they are

function Panel({ title, description, onClose, children }: { title: string; description?: string; onClose?: () => void; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-4 rounded-card border border-border bg-surface p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {description && <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">{description}</p>}
        </div>
        {onClose && (
          <Button type="button" variant="ghost" size="icon-sm" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}>
            <X aria-hidden />
          </Button>
        )}
      </div>
      {children}
    </section>
  );
}

/** Says plainly that there is no transcript and how to get one. Shown for video and audio when the run could not make one. */
function TranscriptNotice({ creative, onSidecar }: { creative: Creative; onSidecar: () => void }) {
  const t = creative.analysis?.transcribe;
  if (!t || (t.status !== "unavailable" && t.status !== "failed")) return null;
  return (
    <div role="status" className="space-y-2 rounded-card border border-warning/30 bg-warning-soft/70 px-4 py-3 text-[13.5px]">
      <p className="flex items-center gap-2 font-semibold text-ink">
        <TriangleAlert aria-hidden className="size-4 shrink-0 text-warning" />
        {t.status === "failed" ? `The ${creative.kind} could not be transcribed` : `There is no transcript for this ${creative.kind}`}
      </p>
      {t.message && <p className="text-ink">{t.message}</p>}
      <p className="max-w-[68ch] text-ink-body">
        The scenes below carry no spoken lines, and what is said in the {creative.kind} has not been read by anyone or anything. To add a transcript, upload the {creative.kind} again with an SRT or
        WebVTT file as its sidecar and run X-Ray on it. The lines are then labelled as yours, not as a transcription.
      </p>
      <Button type="button" variant="outline" size="sm" onClick={onSidecar}>
        Upload again with a sidecar
      </Button>
    </div>
  );
}

/** One creative: its run, scene timeline, the selected scene, evidence and the Indic text preview. */
function Workbench({ creativeId, onSidecar }: { creativeId: string; onSidecar: () => void }) {
  const { campaign } = useCampaign();
  const router = useRouter();
  const creative = useCreative(creativeId);
  const c = creative.data;
  const run = useRun(c?.latest_run_id);
  const scenes = useScenes(creativeId, c?.current_run_id ?? null);
  const rerun = useStartXRay(campaign.id);
  const [picked, setPicked] = useState<string | null>(null);

  if (creative.isError) return <ErrorState error={creative.error} onRetry={() => void creative.refetch()} />;
  if (!c) return <LoadingState label="Opening the creative…" />;

  const list = scenes.data ?? [];
  const index = Math.max(0, list.findIndex((s) => s.id === picked));
  const scene = list[index] ?? null;
  const running = isActive(c.status);
  const again = () => rerun.mutate({ assetId: c.asset_id, label: c.label, language: c.language, regionCode: c.region_code });
  const aspect = c.asset.width && c.asset.height ? c.asset.width / c.asset.height : null;
  // The layout's boxes belong to one keyframe of the scene (not always the first): show that frame under them.
  const layout = scene?.layout ?? [];
  const layoutFrame = layout.length ? c.analysis?.frames.find((f) => f.timestamp_ms === layout[0].frame_ms) : undefined;
  const boxes: StageBox[] = layout.length
    ? layout.map((l, i) => ({ id: `${l.role}-${i}`, bbox: l.bbox, label: ROLE_LABEL[l.role], tone: KEPT_ROLES.has(l.role) ? "locked" : "text" }))
    : scene?.anchor.bbox ? [{ id: "anchor", bbox: scene.anchor.bbox, label: "Anchor", tone: "anchor" }] : [];
  const hasLayout = list.some((x) => x.layout.length > 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <h2 className="truncate text-[19px] font-semibold text-ink">{c.label}</h2>
          <p className="type-ledger text-[13px] text-ink-secondary">
            {KIND_LABEL[c.kind]}
            {c.asset.filename !== c.label && <> · {c.asset.filename}</>}
            {c.region_code && <> · {c.region_code}</>}
            {c.language && <> · spoken {c.language}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          {hasLayout && !running && (
            <UseXRayLayoutButton campaignId={campaign.id} size="sm" variant="outline" onCreated={(id) => router.push(`/app/c/${campaign.id}/studio?tab=elements&v=${id}`)} />
          )}
          <Button variant="outline" size="sm" onClick={again} disabled={running || rerun.isPending}>
            <Play aria-hidden />
            {running ? "Running…" : "Run again"}
          </Button>
        </div>
      </div>
      {rerun.error && <ErrorState error={rerun.error} onRetry={again} />}

      {c.latest_run_id && <RunStatusPanel run={run.data} operation="Creative X-Ray" onRetry={again} />}
      <TranscriptNotice creative={c} onSidecar={onSidecar} />

      {scenes.isError ? (
        <ErrorState error={scenes.error} onRetry={() => void scenes.refetch()} />
      ) : !scene ? (
        <div className="rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-5 py-5 text-[13.5px] text-ink-secondary">
          <p className="text-[15px] font-semibold text-ink">{running ? "Reading the creative…" : "There are no scenes to show"}</p>
          <p className="mt-1 max-w-[68ch]">
            {running
              ? "Scenes appear here when the run has finished. The run status above is real: it names the stage the server is in."
              : c.limitations.join(" ") || "This creative has not produced a usable result yet."}
          </p>
        </div>
      ) : (
        <section aria-labelledby="xray-scenes" className="space-y-4">
          <SectionTitle id="xray-scenes" meta={`${plural(list.length, "scene")}${c.duration_ms != null ? ` · ${clock(c.duration_ms)}` : ""}`}>
            {c.kind === "image" ? "The image" : "Scene timeline"}
          </SectionTitle>
          {(c.kind !== "image" || list.length > 1) && <SceneStrip scenes={list} selectedId={scene.id} onSelect={setPicked} />}
          <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 pt-1 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-3">
              <FrameStage
                path={layoutFrame?.url ?? scene.keyframe_url}
                aspect={aspect}
                boxes={boxes}
                alt={`Keyframe of scene ${index + 1} of ${c.label}`}
                empty={c.kind === "audio" ? "Audio has no picture. Its scenes are time spans." : undefined}
              />
              {layout.length > 0 ? (
                <p className="type-meta flex flex-wrap items-center justify-center gap-1.5 text-center">
                  Where the vision model located the text, logo and pack{layoutFrame ? ` (keyframe at ${clock(layoutFrame.timestamp_ms)})` : ""}
                  <ProvenanceTag kind="model_generated" title="The boxes come from the vision model's reading of this keyframe; which part each plays is a model's reading. Code checked the cited ids." />
                </p>
              ) : (
                boxes.length > 0 && <p className="type-meta text-center">The box marks where this scene&apos;s anchor points.</p>
              )}
              {c.kind !== "image" && <Player creative={c} startMs={scene.start_ms} />}
            </div>
            <SceneDetail scene={scene} index={index} total={list.length} creative={c} />
          </div>
        </section>
      )}

      {c.analysis || c.limitations.length > 0 ? (
        <section aria-labelledby="xray-evidence" className="space-y-3">
          <SectionTitle id="xray-evidence">Evidence and limitations</SectionTitle>
          <AnalysisPanel creative={c} />
        </section>
      ) : null}

      {scene && (
        <section aria-labelledby="xray-text" className="space-y-3">
          <SectionTitle id="xray-text" meta={`On ${c.kind === "image" ? "this image" : `scene ${index + 1}`}`}>
            Indic text preview
          </SectionTitle>
          <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
            Check how regional text sits on this frame before anyone edits the creative. The text is set in code with the script&apos;s own font. It is a layout check,
            not a translation, and nothing is saved.
          </p>
          <TextPreviewTool key={scene.id} creative={c} scene={scene} />
        </section>
      )}
    </div>
  );
}

/** Creative X-Ray: upload a creative, run the X-Ray, read it scene by scene. A sub-page of Creative Studio. */
export function XRayPage() {
  const { campaign, project } = useCampaign();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const creatives = useCreatives(campaign.id);
  const uploads = useUploads(project.id);
  const [adding, setAdding] = useState(false);
  const [asset, setAsset] = useState<Asset | null>(null);
  const [focusAsset, setFocusAsset] = useState<string | null>(null);
  const addRef = useRef<HTMLDivElement>(null);

  const list = creatives.data ?? [];
  const pending = (uploads.data ?? []).filter((a) => a.parent_asset_id === null && !list.some((c) => c.asset_id === a.id));
  const fromParam = params.get("creative");
  const selectedId =
    (focusAsset && list.find((c) => c.asset_id === focusAsset)?.id) || (fromParam && list.some((c) => c.id === fromParam) ? fromParam : null) || list[0]?.id || null;
  const empty = creatives.isSuccess && list.length === 0;
  const showAdd = adding || (empty && !focusAsset);

  const select = (id: string) => {
    setFocusAsset(null);
    router.replace(`${pathname}?creative=${id}`, { scroll: false });
  };
  const openAdd = (next: Asset | null) => {
    setAsset(next);
    setAdding(true);
    requestAnimationFrame(() => addRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  };

  return (
    <>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-5">
        <div className="min-w-0 space-y-1.5">
          <Link href={`/app/c/${campaign.id}/studio`} className="inline-flex items-center gap-1 text-[13px] text-ink-secondary hover:text-ink">
            <ArrowLeft aria-hidden className="size-3.5" />
            Creative Studio
          </Link>
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Creative X-Ray</h1>
          <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
            Break a video, image or audio creative into scenes. Every line says whether it was read from the file or reported by a model.
          </p>
          <CampaignFacts />
        </div>
      </header>

      <div className="space-y-6">
        {creatives.isError ? (
          <ErrorState error={creatives.error} onRetry={() => void creatives.refetch()} />
        ) : creatives.isPending ? (
          <LoadingState label="Loading this campaign's creatives…" />
        ) : (
          (list.length > 0 || pending.length > 0) && (
            <CreativePicker creatives={list} pending={pending} selectedId={selectedId} onSelect={select} onAnalyse={openAdd} onAdd={() => openAdd(null)} />
          )
        )}

        {showAdd && (
          <div ref={addRef}>
            <Panel
              title={asset ? "Run Creative X-Ray" : empty ? "Upload a creative to X-Ray" : "Add a creative"}
              description={
                asset
                  ? undefined
                  : "Upload an image, a video of up to 60 seconds, or audio. You get a scene timeline with keyframes, any on-screen text and transcript, and the cultural references a model reported, each labelled."
              }
              onClose={empty ? undefined : () => (setAdding(false), setAsset(null))}
            >
              {asset ? (
                <RunForm
                  key={asset.id}
                  asset={asset}
                  campaignId={campaign.id}
                  demo={project.mode === "demo"}
                  onBack={() => setAsset(null)}
                  onStarted={(assetId) => {
                    setFocusAsset(assetId);
                    setAsset(null);
                    setAdding(false);
                  }}
                />
              ) : (
                <UploadForm projectId={project.id} onUploaded={setAsset} />
              )}
            </Panel>
          </div>
        )}

        {selectedId && <Workbench key={selectedId} creativeId={selectedId} onSidecar={() => openAdd(null)} />}
      </div>
    </>
  );
}
