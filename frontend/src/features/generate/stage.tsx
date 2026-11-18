"use client";

import { ArrowRight, CircleCheck, CircleX, Download, Layers, Play, Replace, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { Button, buttonVariants } from "@/components/ui/button";
import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { cn } from "@/lib/utils";

import { useUseInStudio, type GenerateAssetRef, type GenerateItem, type GenerateKind, type Run } from "./api";
import { LiveStrip, PlayButton, PlayerAudio, useAudioPlayer, Waveform, type Segment } from "./audio";
import { AssetImage, CompareSlider } from "./images";
import { AiTag, Chip, mmss, Notice, RunError, RunLadder, seconds, SourceLine, usd } from "./parts";

const KIND_WORD: Record<GenerateKind, string> = { image: "image", voice: "voice-over", jingle: "jingle" };
const GLINTS: CSSProperties[] = [
  { left: "12%", top: "18%", animationDelay: "0s" },
  { left: "82%", top: "26%", animationDelay: "1.7s" },
  { left: "68%", top: "78%", animationDelay: "3.1s" },
  { left: "24%", top: "70%", animationDelay: "4.2s" },
];

/** The living canvas every result and every working run sits on. */
export function Stage({ children, className, working }: { children: ReactNode; className?: string; working?: boolean }) {
  return (
    <div className={cn("gen-stage", className)}>
      {GLINTS.map((style, i) => (
        <span key={i} aria-hidden className="gen-glint" style={style} />
      ))}
      {working && <span aria-hidden className="gen-sweep" />}
      {children}
    </div>
  );
}

export function EmptyStage({ kind }: { kind: GenerateKind }) {
  return (
    <Stage className="grid min-h-[22rem] place-items-center p-8 text-center sm:min-h-[26rem]">
      <div className="max-w-sm space-y-2">
        <Sparkles aria-hidden className="mx-auto size-6 text-pink" />
        <p className="type-title text-[22px] text-ink">Your {KIND_WORD[kind]} appears here</p>
        <p className="text-[14px] text-ink-secondary">Set it up on the left and run it. Every result is kept in the gallery below with the model, prompt version and cost that made it.</p>
      </div>
    </Stage>
  );
}

export function WorkingStage({ kind, run }: { kind: GenerateKind; run: Run | undefined }) {
  return (
    <Stage working className="grid min-h-[22rem] place-items-center p-8 sm:min-h-[26rem]">
      <div className="w-full max-w-sm space-y-4 rounded-xl bg-surface/80 p-5 shadow-raised">
        <p className="type-title text-[20px] text-ink">Making your {KIND_WORD[kind]}</p>
        <RunLadder kind={kind} run={run} />
        <p className="type-meta">{run?.progress?.message ?? "Starting…"}</p>
      </div>
    </Stage>
  );
}

function Download_({ asset, label }: { asset: GenerateAssetRef; label: string }) {
  const src = useAssetObjectUrl({ id: asset.asset_id, content_url: asset.url });
  return src ? (
    <a href={src} download={asset.filename} className={buttonVariants({ variant: "outline" })}>
      <Download aria-hidden />
      {label}
    </a>
  ) : (
    <Button variant="outline" disabled>
      <Download aria-hidden />
      {label}
    </Button>
  );
}

/** Download, add to a Studio version, and (for an image) use as the reference of the next one. */
function Actions({ campaignId, item, onReference }: { campaignId: string; item: GenerateItem; onReference: (assetId: string) => void }) {
  const use = useUseInStudio(campaignId);
  const added = use.isSuccess || item.studio_version_ids.length > 0;
  if (!item.asset) return null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Download_ asset={item.asset} label={`Download ${KIND_WORD[item.kind]}`} />
        <Button variant="outline" disabled={use.isPending || use.isSuccess} onClick={() => use.mutate({ runId: item.id, versionId: null })}>
          <Layers aria-hidden />
          {use.isPending ? "Adding…" : "Use in Studio"}
        </Button>
        {item.kind === "image" && (
          <Button variant="outline" onClick={() => onReference(item.asset!.asset_id)}>
            <Replace aria-hidden />
            Use as reference
          </Button>
        )}
        {added && (
          <Link href={`/app/c/${campaignId}/studio`} className="inline-flex items-center gap-1 text-[13.5px] font-medium text-rose underline-offset-2 hover:underline">
            Added as an element. Open Creative Studio
            <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </div>
      {use.isError && <Notice>{use.error.message}</Notice>}
    </div>
  );
}

function Provenance({ item }: { item: GenerateItem }) {
  const facts: [string, string][] = [
    ["Model", item.model ? `${item.model}${item.location ? ` · ${item.location}` : ""}` : "none (saved output)"],
    ["Prompt version", item.prompt_version],
    ["Estimated cost", item.source === "demo_fixture" ? "none: nothing was charged" : usd(item.estimated_cost_usd)],
    ["Model time", item.latency_ms ? seconds(item.latency_ms) : "n/a"],
    ["Run", item.id],
  ];
  const request = Object.entries(item.request).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0));
  return (
    <details className="rounded-lg border border-border bg-surface px-3.5 py-2.5 text-[13.5px]">
      <summary className="cursor-pointer font-medium text-ink">How this was made</summary>
      <dl className="mt-3 grid gap-x-4 gap-y-1.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-secondary">{k}</dt>
            <dd className="min-w-0 break-words text-ink">{v}</dd>
          </div>
        ))}
        {request.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-secondary">{k.replaceAll("_", " ")}</dt>
            <dd className="min-w-0 break-words text-ink">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
      {item.prompt && (
        <div className="mt-3 space-y-1">
          <p className="text-ink-secondary">Prompt sent to the model</p>
          <p className="rounded-lg bg-surface-muted p-3 text-[13px] leading-relaxed whitespace-pre-wrap text-ink-body">{item.prompt}</p>
        </div>
      )}
    </details>
  );
}

function Limitations({ item }: { item: GenerateItem }) {
  if (!item.limitations.length) return null;
  return (
    <ul className="space-y-1 text-[13px] text-ink-secondary">
      {item.limitations.map((l) => (
        <li key={l}>{l}</li>
      ))}
    </ul>
  );
}

type ImageView = "finished" | "scene" | "compare";

function ImageStage({ item }: { item: GenerateItem }) {
  const detail = item.image!;
  const [view, setView] = useState<ImageView>("finished"); // the finished creative first; the reference comparison is one chip away
  const aspect = detail.width / detail.height;
  const shown = view === "scene" ? detail.scene : item.asset!;
  return (
    <div className="space-y-3">
      <div role="group" aria-label="What to look at" className="flex flex-wrap gap-2">
        <Chip pressed={view === "finished"} onClick={() => setView("finished")}>
          Finished
        </Chip>
        <Chip pressed={view === "scene"} onClick={() => setView("scene")}>
          Scene only
        </Chip>
        {detail.reference && (
          <Chip pressed={view === "compare"} onClick={() => setView("compare")}>
            Reference and result
          </Chip>
        )}
      </div>
      <Stage className="grid min-h-[22rem] place-items-center p-3 sm:p-5">
        {view === "compare" && detail.reference ? (
          <CompareSlider before={detail.reference} after={item.asset!} beforeLabel="Reference" afterLabel="Result" aspect={aspect} />
        ) : (
          <div key={view} className="gen-arrive h-[min(68vh,40rem)] w-full">
            <AssetImage asset={shown} alt={view === "scene" ? "The scene before the logo, product and headline were placed in code" : `${item.title}, finished`} className="rounded-lg shadow-float" eager />
          </div>
        )}
      </Stage>
      <div className="flex flex-wrap items-center gap-2">
        {view === "scene" ? <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">Model interpretation</Tag> : <AiTag>AI proposal</AiTag>}
        <span className="type-meta">
          {detail.width} x {detail.height} px · {detail.format}
        </span>
      </div>
      <ul className="grid gap-1.5 sm:grid-cols-2" aria-label="Checks computed in code">
        {detail.checks.map((c) => (
          <li key={c.id} className="flex items-start gap-2 text-[13.5px]">
            {c.passed ? <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" /> : <CircleX aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />}
            <span className="text-ink-body">
              <span className="sr-only">{c.passed ? "Passed: " : "Flagged: "}</span>
              {c.label}
              {c.detail && <span className="type-meta block">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
      {detail.headline && (
        <p lang={detail.headline.language ?? undefined} className="text-[14px] text-ink-body">
          Headline: <span className="font-medium text-ink">{detail.headline.text}</span>
          <span className="type-meta"> · drawn in code, {detail.headline.font_size} px</span>
        </p>
      )}
    </div>
  );
}

function AudioStage({ item, peaks, durationMs, segments, children }: { item: GenerateItem; peaks: number[]; durationMs: number; segments: Segment[]; children?: (player: ReturnType<typeof useAudioPlayer>) => ReactNode }) {
  const player = useAudioPlayer(item.asset, segments);
  return (
    <div className="space-y-3">
      <Stage className="space-y-3 p-4 sm:p-6">
        <PlayerAudio bind={player.bind} src={player.src} />
        <div className="rounded-xl bg-surface/80 p-3 shadow-raised">
          <Waveform peaks={peaks} durationMs={durationMs} player={player} segments={segments} label={`${item.title}: position in the track`} />
        </div>
        <LiveStrip player={player} />
        <div className="flex flex-wrap items-center gap-3">
          <PlayButton player={player} durationMs={durationMs} label={item.title} />
          {item.kind === "voice" ? <AiTag>AI proposal</AiTag> : <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">Model interpretation</Tag>}
        </div>
      </Stage>
      {children?.(player)}
    </div>
  );
}

function VoiceStage({ item }: { item: GenerateItem }) {
  const voice = item.voice!;
  const segments: Segment[] = voice.lines.filter((l) => l.spoken).map((l) => ({ index: l.index, start: l.start_ms, end: l.end_ms, label: l.text }));
  return (
    <AudioStage item={item} peaks={voice.peaks} durationMs={voice.total_duration_ms} segments={segments}>
      {(player) => (
        <ol className="space-y-2" aria-label="Lines with their timings">
          {voice.lines.map((l) => (
            <li
              key={l.index}
              className={cn(
                "flex items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors",
                player.active === l.index ? "border-primary bg-pop-soft" : "border-border bg-surface",
              )}
            >
              <button
                type="button"
                disabled={!l.spoken || !player.src}
                onClick={() => player.playRange(l.start_ms, l.end_ms)}
                aria-label={`Play line ${l.index + 1}`}
                className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-surface-raised text-ink shadow-clay outline-none hover:bg-surface-muted focus-visible:ring-3 focus-visible:ring-ring/30 disabled:opacity-40 max-sm:size-11"
              >
                <Play aria-hidden className="size-3.5" />
              </button>
              <div className="min-w-0 flex-1 space-y-1">
                <p lang={l.language} className="text-[15px] leading-relaxed text-ink">
                  {l.text}
                </p>
                {l.back_translation && (
                  <p className="text-[13px] text-ink-secondary">
                    <span className="font-medium">English back-translation:</span> {l.back_translation}
                  </p>
                )}
                {l.problems.map((p) => (
                  <p key={p} className="text-[13px] text-danger">
                    {p}
                  </p>
                ))}
                <p className="type-meta tabular-nums sm:hidden">{l.spoken ? `${mmss(l.start_ms)} to ${mmss(l.end_ms)}` : "not spoken"}</p>
              </div>
              <span className="type-meta shrink-0 tabular-nums max-sm:hidden">
                {l.spoken ? `${mmss(l.start_ms)} to ${mmss(l.end_ms)}` : "not spoken"}
              </span>
            </li>
          ))}
        </ol>
      )}
    </AudioStage>
  );
}

function JingleStage({ item }: { item: GenerateItem }) {
  const jingle = item.jingle!;
  return (
    <AudioStage item={item} peaks={jingle.peaks} durationMs={jingle.duration_ms} segments={[]}>
      {() => (
        <p className="type-meta">
          {mmss(jingle.duration_ms)} cut from a {jingle.generated_seconds.toFixed(0)} s clip · {(jingle.sample_rate / 1000).toFixed(0)} kHz · {jingle.channels === 2 ? "stereo" : "mono"} · mood: {jingle.mood}
          {jingle.festival ? ` · festival: ${jingle.festival}` : ""}
          {jingle.instruments.length ? ` · ${jingle.instruments.join(", ")}` : ""}
        </p>
      )}
    </AudioStage>
  );
}

/** One generated item on the big canvas, with its checks, its provenance and what to do with it. */
export function ItemView({ campaignId, item, onReference }: { campaignId: string; item: GenerateItem; onReference: (assetId: string) => void }) {
  if (item.status === "failed" || !item.asset) {
    return (
      <div className="space-y-3">
        <RunError error={item.error} />
        <Limitations item={item} />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="type-title text-[22px] text-ink">{item.title}</h2>
        {item.status === "partial" && <Tag className="border-warning/30 bg-warning-soft text-warning">Finished with flags</Tag>}
      </div>
      {item.kind === "image" && item.image && <ImageStage item={item} />}
      {item.kind === "voice" && item.voice && <VoiceStage item={item} />}
      {item.kind === "jingle" && item.jingle && <JingleStage item={item} />}
      <Actions campaignId={campaignId} item={item} onReference={onReference} />
      <Limitations item={item} />
      <Provenance item={item} />
      <SourceLine>
        {item.source === "demo_fixture"
          ? `Source: saved demonstration ${KIND_WORD[item.kind]}, made once with ${item.model}. No model was called for this run.`
          : `Source: ${item.model}${item.location ? ` (${item.location})` : ""}, prompt ${item.prompt_version}, ${usd(item.estimated_cost_usd)} estimated.`}
      </SourceLine>
    </div>
  );
}
