"use client";

import { Check, TriangleAlert, X } from "lucide-react";
import { useState } from "react";

import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { formatDate } from "@/lib/format";

import type { RemakeOutput } from "./api";
import { AiTag, LockChip, Notice, SourceLine, mmss, usd } from "./parts";

const KB = 1024;
const size = (bytes: number) => (bytes >= KB * KB ? `${(bytes / (KB * KB)).toFixed(1)} MB` : `${Math.round(bytes / KB)} KB`);

/** The finished clip in a player, its provenance, and the checks computed in code from the delivered file. */
export function VideoResult({ output }: { output: RemakeOutput }) {
  const v = output.video;
  const [silent, setSilent] = useState(false);
  const file = v ? (silent ? { id: v.silent_asset_id, content_url: v.silent_url } : { id: v.video_asset_id, content_url: v.video_url }) : null;
  const src = useAssetObjectUrl(file);
  const poster = useAssetObjectUrl(v?.start_frame_asset_id && v.start_frame_url ? { id: v.start_frame_asset_id, content_url: v.start_frame_url } : null);
  if (!v) return <Notice>This remake has no clip.</Notice>;
  const demo = v.source === "demo_fixture";
  return (
    <section aria-label="Clip result" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold text-ink">Regional clip <AiTag /></h2>
        <SourceLine>
          {demo ? "Saved demonstration clip" : `${v.model} · ${v.location ?? "us-central1"}`} · {v.seconds} s · {v.resolution} · {formatDate(output.created_at)}
          {demo ? "" : ` · ${usd(output.estimated_cost_usd)} estimated`}
        </SourceLine>
      </div>

      <div className="space-y-2 rounded-card border border-border bg-surface p-3.5">
        {src ? (
          <video
            key={file?.id}
            src={src}
            poster={poster ?? undefined}
            controls
            playsInline
            preload="metadata"
            aria-label={`Regional clip for ${output.region_code}${silent || !v.with_voiceover ? "" : ", with the voice-over"}`}
            className="mx-auto block max-h-[34rem] w-auto max-w-full rounded-lg bg-black"
          />
        ) : (
          <p className="type-meta">Loading the clip…</p>
        )}
        <p className="type-meta">
          {v.duration_ms != null ? `${mmss(v.duration_ms)} (${(v.duration_ms / 1000).toFixed(1)} s)` : `${v.seconds} s asked for`}
          {v.width && v.height ? ` · ${v.width}×${v.height}` : ""} · {size(v.size_bytes)} · {v.with_voiceover && !silent ? "voice-over joined" : "no audio"}
        </p>
        {v.with_voiceover && (
          <button type="button" aria-pressed={silent} onClick={() => setSilent((s) => !s)} className="text-[12.5px] font-medium text-primary underline underline-offset-2">
            {silent ? "Play with the voice-over" : "Play the clip as the model delivered it (no audio)"}
          </button>
        )}
      </div>

      {v.kept_regions.length > 0 && (
        <section aria-label="Brand elements" className="space-y-2 rounded-card border border-border bg-surface px-3.5 py-3">
          <h3 className="text-[13.5px] font-semibold text-ink">Brand elements in the start frame</h3>
          <ul className="flex flex-wrap gap-1.5">
            {v.kept_regions.map((r) => (
              <li key={r.element_id}>
                <LockChip>{r.kind}</LockChip>
              </li>
            ))}
          </ul>
          <p className="text-[13px] text-ink-body">
            They were restored exactly in the start frame. A video model cannot guarantee they stay unchanged from frame to frame, so look at the whole clip before you use it.
          </p>
        </section>
      )}

      {v.checks.length > 0 && (
        <section aria-label="Checks computed in code" className="rounded-card border border-border bg-surface">
          <h3 className="border-b border-border px-3.5 py-2.5 text-[13.5px] font-semibold text-ink">
            Checks of the file <span className="type-meta font-normal">read with ffprobe, not by a model</span>
          </h3>
          <ul className="divide-y divide-border">
            {v.checks.map((c) => (
              <li key={c.name} className="flex items-start justify-between gap-3 px-3.5 py-2 text-[13px]">
                <span className="min-w-0">
                  <span className="text-ink">{c.name}</span>
                  <span className="block type-meta">{c.detail}</span>
                </span>
                <span className={c.passed ? "inline-flex shrink-0 items-center gap-1 text-[12.5px] text-success" : "inline-flex shrink-0 items-center gap-1 text-[12.5px] text-warning"}>
                  {c.passed ? <Check aria-hidden className="size-3.5" /> : <X aria-hidden className="size-3.5" />}
                  {c.passed ? "Passed" : "Flagged"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {output.limitations.length > 0 && (
        <ul className="space-y-1.5">
          {output.limitations.map((n) => (
            <li key={n} className="flex items-start gap-1.5 text-[12.5px] text-ink-secondary">
              <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {n}
            </li>
          ))}
        </ul>
      )}

      <details className="rounded-card border border-border bg-surface px-3.5 py-2.5 text-[13px] text-ink-body">
        <summary className="cursor-pointer font-medium text-ink">Prompt and provenance</summary>
        <dl className="mt-2.5 grid gap-1.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="type-meta">Model</dt>
          <dd>{demo ? `${v.model ?? "Veo"} (saved demonstration clip, generated once)` : `${v.model} · ${v.location}`}</dd>
          <dt className="type-meta">Length and size</dt>
          <dd>{v.seconds} s asked for · {v.resolution} · {v.aspect_ratio ?? "no aspect ratio"}</dd>
          <dt className="type-meta">Estimated cost</dt>
          <dd>{demo ? "none: saved clip" : `${usd(output.estimated_cost_usd)} from the price table, not a billed amount`}</dd>
          <dt className="type-meta">Start frame</dt>
          <dd>{{ remake_scene: "The Remake: Visuals scene with the locked regions restored, no text", asset: "An image chosen for this run", demo_fixture: "The saved demonstration scene with the locked regions restored, no text", none: "None: made from the prompt alone" }[v.start_source]}</dd>
          <dt className="type-meta">Prompt version</dt>
          <dd className="font-mono text-[12.5px]">{v.prompt_version}</dd>
          <dt className="type-meta">Version created</dt>
          <dd className="font-mono text-[12.5px]">{output.result_version_id}</dd>
          <dt className="type-meta">Run</dt>
          <dd className="font-mono text-[12.5px]">{output.run_id ?? "none"}</dd>
          {v.operation_id && (<><dt className="type-meta">Provider operation</dt><dd className="font-mono text-[12.5px]">{v.operation_id}</dd></>)}
          {v.direction && (<><dt className="type-meta">Art direction</dt><dd>{v.direction}</dd></>)}
          {v.prompt && (<><dt className="type-meta">Sent to the model</dt><dd className="whitespace-pre-wrap">{v.prompt}</dd></>)}
          {v.negative_prompt && (<><dt className="type-meta">Kept out</dt><dd>{v.negative_prompt}</dd></>)}
        </dl>
      </details>
    </section>
  );
}
