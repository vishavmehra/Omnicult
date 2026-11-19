"use client";

import { CircleAlert, CircleCheck, CircleDashed, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { LedgerList } from "@/features/workspaces/parts";
import { formatBytes } from "@/features/assets/asset-uploader";
import { humanize, shownModel } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { Creative } from "./api";
import { clock } from "./parts";

function Status({ Icon, tone, children }: { Icon: LucideIcon; tone: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-medium", tone)}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

const source = (provider: string | null, model: string | null) => [shownModel(provider), shownModel(model)].filter(Boolean).join(" · ");

/** The transcript row: what the run found out about speech, in plain words, never a guess. */
function TranscriptStatus({ creative }: { creative: Creative }) {
  const t = creative.analysis?.transcribe;
  if (!t) return null;
  switch (t.status) {
    case "transcribed":
      return (
        <>
          <Status Icon={CircleCheck} tone="text-success">Transcribed</Status>
          <span className="block text-ink-secondary">By {source(t.provider, t.model_id) || "a transcription model"}. Machine transcription has not been checked by a person.</span>
        </>
      );
    case "from_sidecar":
      return (
        <>
          <Status Icon={CircleCheck} tone="text-success">From your sidecar</Status>
          <span className="block text-ink-secondary">The lines come from the SRT or WebVTT file you uploaded. Nothing was transcribed by a model.</span>
        </>
      );
    case "not_applicable":
      return <span className="text-ink-secondary">Not applicable: an image has no speech.</span>;
    case "failed":
      return (
        <>
          <Status Icon={CircleAlert} tone="text-danger">Transcription failed</Status>
          {t.message && <span className="block text-ink-secondary">{t.message}</span>}
        </>
      );
    default:
      return (
        <>
          <Status Icon={TriangleAlert} tone="text-warning">Unavailable</Status>
          {t.message && <span className="block text-ink-secondary">{t.message}</span>}
        </>
      );
  }
}

/** Evidence and limits of the current run: what was read, how, and what is missing or was removed. */
export function AnalysisPanel({ creative }: { creative: Creative }) {
  const a = creative.analysis;
  if (!a) {
    return <LimitationList items={creative.limitations} title="Why there is no analysis yet" />;
  }
  const { probe, vision } = a;
  const dropped = Object.entries(a.dropped).filter(([, n]) => n > 0);
  const steps = creative.run_metadata?.steps ?? [];
  return (
    <div className="space-y-4">
      <LedgerList
        rows={[
          {
            label: "File",
            value: (
              <span className="type-ledger">
                {creative.asset.filename} · {formatBytes(creative.asset.size_bytes)}
                {probe.container && <> · {probe.container}</>}
                {probe.duration_ms != null && <> · {clock(probe.duration_ms)}</>}
                {probe.width && probe.height && <> · {probe.width} x {probe.height}</>}
                {probe.fps != null && <> · {probe.fps} fps</>}
                {(probe.video_codec || probe.audio_codec) && <> · {[probe.video_codec, probe.audio_codec].filter(Boolean).join(" + ")}</>}
              </span>
            ),
          },
          ...(probe.kind !== "image"
            ? [{ label: "Transcript", value: <TranscriptStatus creative={creative} /> }]
            : []),
          {
            label: "Frames",
            value:
              vision.status === "analyzed" ? (
                <>
                  <Status Icon={CircleCheck} tone="text-success">Read by a vision model</Status>
                  <span className="block text-ink-secondary">
                    {a.frames.length} {a.frames.length === 1 ? "frame" : "frames"}{source(vision.provider, vision.model_id) && ` · ${source(vision.provider, vision.model_id)}`}
                  </span>
                </>
              ) : (
                <>
                  <Status Icon={CircleDashed} tone="text-ink-secondary">{vision.status === "failed" ? "Reading failed" : "Not read by a model"}</Status>
                  {vision.message && <span className="block text-ink-secondary">{vision.message}</span>}
                </>
              ),
          },
          {
            label: "Removed by code",
            value: dropped.length ? (
              <>
                {dropped.map(([k, n]) => `${humanize(k)}: ${n}`).join(", ")}
                <span className="block text-ink-secondary">Model items dropped because they could not be found in the frame observations or the transcript.</span>
              </>
            ) : (
              <span className="text-ink-secondary">Nothing. Every kept item was found in the frames or transcript.</span>
            ),
            muted: !dropped.length,
          },
          ...(a.sidecar_notes ? [{ label: "Your notes", value: <span className="whitespace-pre-line">{a.sidecar_notes}</span> }] : []),
        ]}
      />
      <LimitationList items={a.limitations} title="Limitations of this X-Ray" />
      <p className="max-w-[68ch] text-[12.5px] text-ink-secondary">
        Read from frame, Transcribed and Your sidecar come from the file itself. Model observation and Model interpretation are a model&apos;s reading: the frames and
        lines they cite were checked in code, the reading was not.
      </p>
      {steps.length > 0 && (
        <details className="rounded-card border border-border bg-surface">
          <summary className="cursor-pointer px-4 py-2.5 text-[13.5px] font-semibold text-ink">How this was produced</summary>
          <div className="overflow-x-auto border-t border-border">
            <table className="type-ledger w-full min-w-[34rem] text-left text-[12.5px]">
              <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Stage</th>
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 font-medium">Provider and model</th>
                  <th scope="col" className="px-3 py-2 font-medium">Prompt</th>
                  <th scope="col" className="px-3 py-2 font-medium">Took</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {steps.map((s, i) => (
                  <tr key={i}>
                    <td className="px-3 py-2 text-ink">{humanize(s.stage)}</td>
                    <td className="px-3 py-2 text-ink-body">{humanize(s.status)}</td>
                    <td className="px-3 py-2 text-ink-secondary">{source(s.provider ?? null, s.model_id ?? null) || "Code only"}</td>
                    <td className="px-3 py-2 font-mono text-[11.5px] text-ink-muted">{s.prompt_version ?? "n/a"}</td>
                    <td className="px-3 py-2 text-ink-secondary">{s.latency_ms != null ? `${(s.latency_ms / 1000).toFixed(1)} s` : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
