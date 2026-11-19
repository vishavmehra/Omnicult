"use client";

import { useEffect, useState } from "react";

import { Field } from "@/components/forms/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useProjectImages, useRemakeRun, type RemakeCapabilities, type RemakeOutput, type VersionSummary } from "./api";
import { CostConfirm, LockChip, Notice, RunProgress, SELECT, usd } from "./parts";
import { useStartVideo, useVideoPreview, type VideoPreview } from "./video-api";
import { VideoResult } from "./video-result";

function useDebounced<T>(value: T, ms = 500): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** Setup for one regional clip: version, length, start frame and direction, the exact prompt and cost, then run. */
export function VideoPanel({
  campaignId,
  projectId,
  demo,
  caps,
  versions,
  outputs,
}: {
  campaignId: string;
  projectId: string;
  demo: boolean;
  caps: RemakeCapabilities;
  versions: VersionSummary[];
  outputs: RemakeOutput[];
}) {
  const clips = outputs.filter((o) => o.kind === "video");
  const [versionId, setVersionId] = useState<string | null>(null);
  const [seconds, setSeconds] = useState<number>(caps.video_default_seconds);
  const [startAssetId, setStartAssetId] = useState("");
  const [direction, setDirection] = useState("");
  const [voiceover, setVoiceover] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [viewId, setViewId] = useState<string | null>(null);
  const typed = useDebounced(direction.trim());

  const version = versions.find((v) => v.id === versionId) ?? versions[versions.length - 1] ?? null;
  const hasTarget = Boolean(version?.region_code && version?.language);
  const images = useProjectImages(projectId);
  const request =
    version && version.region_code && version.language
      ? {
          version_id: version.id,
          region_code: version.region_code,
          language: version.language,
          seconds: (demo ? caps.video_default_seconds : seconds) as 4 | 6 | 8,
          start_asset_id: !demo && startAssetId ? startAssetId : null,
          direction: !demo && typed ? typed : null,
          add_voiceover: voiceover,
        }
      : null;
  const preview = useVideoPreview(campaignId, request);
  const plan = preview.data;
  const start = useStartVideo(campaignId);
  const run = useRemakeRun(campaignId, runId);

  const working = start.isPending || (run.data !== undefined && (run.data.status === "queued" || run.data.status === "running"));
  const videoOff = !demo && !caps.video.configured;
  const rate = caps.video_price_per_second_usd;
  const blocked = !version
    ? "This campaign has no version yet."
    : !hasTarget
      ? "Choose a version that is already adapted to a region and language."
      : (plan?.blocked_reason ?? null);
  const canRun = Boolean(plan) && !blocked && !videoOff && (demo || confirmed) && !working && !preview.isFetching;
  const shown = clips.find((o) => o.run_id === runId) ?? clips.find((o) => o.id === viewId) ?? (runId ? undefined : clips[0]);

  function submit() {
    if (!request || !plan) return;
    start.mutate(
      { ...request, confirm_cost: !demo && confirmed },
      { onSuccess: (accepted) => { setRunId(accepted.run_id); setViewId(null); setConfirmed(false); } },
    );
  }

  if (!versions.length) {
    return <EmptyState title="No version to make a clip from yet" description="Remake works on a version of the campaign. Create or open one in Creative Studio first." />;
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <form
        className="space-y-4 self-start rounded-card border border-border bg-surface p-4 shadow-card"
        onSubmit={(e) => { e.preventDefault(); submit(); }}
        aria-label="Remake: Video setup"
      >
        <Field label="Version" htmlFor="rm-version" required>
          <select id="rm-version" className={SELECT} value={version?.id ?? ""} onChange={(e) => setVersionId(e.target.value)}>
            {[...versions].reverse().map((v) => (
              <option key={v.id} value={v.id}>{v.label} · {v.region_code ?? "no region"} · {v.language ?? "no language"}</option>
            ))}
          </select>
        </Field>
        <p className="type-ledger text-[12.5px] text-ink-muted">
          Target <span className="text-ink-body">{version?.region_code ?? "none"}</span> in <span className="text-ink-body">{version?.language ?? "none"}</span>, taken from the version.
        </p>

        {demo ? (
          <p className="text-[13px] text-ink-secondary">The clip is {caps.video_default_seconds} s, 720p, for {caps.demo_video_regions.join(", ") || "no region"}.</p>
        ) : (
          <Field label="Length" htmlFor="rm-seconds" hint="Billed per generated second. Eight seconds needs a higher per-run AI budget.">
            <select id="rm-seconds" className={SELECT} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>
              {caps.video_seconds.map((s) => {
                const over = rate != null && caps.run_budget_usd > 0 && s * rate > caps.run_budget_usd;
                return (
                  <option key={s} value={s} disabled={over}>
                    {s} s{rate != null ? ` · about ${usd(s * rate)}` : ""}{over ? " · over the per-run budget" : ""}
                  </option>
                );
              })}
            </select>
          </Field>
        )}

        {!demo && (images.data ?? []).length > 0 && (
          <Field label="Start frame" htmlFor="rm-start" hint="Automatic uses the Remake: Visuals scene in this version, with the locked regions restored.">
            <select id="rm-start" className={SELECT} value={startAssetId} onChange={(e) => setStartAssetId(e.target.value)}>
              <option value="">Automatic</option>
              {(images.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
            </select>
          </Field>
        )}

        {!demo && (
          <Field label="Art direction" htmlFor="rm-direction" hint="Your words, added to the prompt as yours. Never text to draw.">
            <Textarea id="rm-direction" rows={3} maxLength={400} value={direction} onChange={(e) => setDirection(e.target.value)} />
          </Field>
        )}

        {plan?.voiceover && (
          <label className={cn("flex items-start gap-2.5 text-[13.5px] text-ink-body", !plan.voiceover.will_join && "opacity-80")}>
            <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-primary" checked={voiceover} onChange={(e) => setVoiceover(e.target.checked)} />
            <span>
              Join the voice-over of this version{plan.voiceover.duration_ms ? ` (${(plan.voiceover.duration_ms / 1000).toFixed(1)} s)` : ""}
              <span className="type-meta block">{plan.voiceover.note}</span>
            </span>
          </label>
        )}

        {videoOff && <Notice>No video model is configured on this server, so Remake: Video cannot run here.</Notice>}
        {blocked && !videoOff && <Notice tone="info">{blocked}</Notice>}
        <CostConfirm demo={demo} estimate={plan?.estimated_cost_usd} what={`one ${request?.seconds ?? seconds} s video clip`} checked={confirmed} onChange={setConfirmed} />
        <Button type="submit" disabled={!canRun} className="w-full">
          {working ? "Working…" : demo ? "Show the clip" : `Make a ${request?.seconds ?? seconds} s clip`}
        </Button>
        {start.error && <ErrorState error={start.error} />}
      </form>

      <div className="min-w-0 space-y-4">
        <Plan plan={plan} loading={preview.isLoading} error={preview.error} demo={demo} onRetry={() => void preview.refetch()} />
        {runId && <RunProgress run={run.data} onRetry={submit} />}
        {shown ? (
          <VideoResult output={shown} />
        ) : runId && working ? (
          <LoadingState label="Generating the clip. This usually takes a minute or two…" />
        ) : !runId ? (
          <EmptyState title="No clip yet" description="Check the start frame and the prompt, then make the clip. The player, the checks and the provenance appear here." />
        ) : null}
        {clips.length > 1 && (
          <section aria-label="Earlier clips" className="space-y-1.5">
            <h3 className="text-[13px] font-semibold text-ink-secondary">Earlier clips</h3>
            <ul className="divide-y divide-border rounded-card border border-border bg-surface">
              {clips.map((o) => (
                <li key={o.id}>
                  <button
                    type="button"
                    onClick={() => { setRunId(null); setViewId(o.id); }}
                    aria-current={o.id === shown?.id ? "true" : undefined}
                    className={cn("flex w-full items-center justify-between gap-3 px-3.5 py-2 text-left text-[13px] hover:bg-surface-muted", o.id === shown?.id && "bg-surface-muted")}
                  >
                    <span className="text-ink-body">{o.region_code} · {o.video?.seconds} s · {formatDate(o.created_at)}</span>
                    <span className="type-meta">{o.passed ? "checks passed" : "checks flagged"} · {usd(o.estimated_cost_usd)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

/** The exact start frame and prompt a run would send, with the one honest warning about brand elements. */
function Plan({ plan, loading, error, demo, onRetry }: { plan: VideoPreview | undefined; loading: boolean; error: unknown; demo: boolean; onRetry: () => void }) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading || !plan) return <LoadingState label="Preparing the start frame…" />;
  const frame = plan.start_frame;
  return (
    <section aria-label="What the clip starts from" className="space-y-3 rounded-card border border-border bg-surface p-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[15px] font-semibold text-ink">Start frame and prompt</h2>
      </div>
      <div className="grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]">
        <figure className="space-y-1.5">
          {frame.preview_jpeg_base64 ? (
            // eslint-disable-next-line @next/next/no-img-element -- a reduced preview returned inline by the API
            <img
              src={`data:image/jpeg;base64,${frame.preview_jpeg_base64}`}
              alt="The start frame of the clip, without any text"
              className="mx-auto block max-h-80 w-auto max-w-full rounded-lg border border-border"
            />
          ) : (
            <div className="grid h-40 w-40 place-items-center rounded-lg border border-dashed border-border text-center text-[12.5px] text-ink-muted">No start frame</div>
          )}
          <figcaption className="type-meta max-w-[18rem]">{frame.description}{frame.width && frame.height ? ` ${frame.width}×${frame.height}.` : ""}</figcaption>
        </figure>
        <div className="min-w-0 space-y-2.5">
          {plan.kept_regions.length > 0 && (
            <div className="space-y-1.5">
              <ul className="flex flex-wrap gap-1.5">
                {plan.kept_regions.map((r) => (
                  <li key={r.element_id}><LockChip>{r.kind} kept in the frame</LockChip></li>
                ))}
              </ul>
              <p className="text-[12.5px] text-ink-secondary">A video model cannot guarantee these stay unchanged from frame to frame. The clip has no on-screen text; any text is added in code.</p>
            </div>
          )}
          <div className="space-y-1">
            <h3 className="text-[12.5px] font-medium text-ink-secondary">{demo ? "Prompt" : "Prompt sent to the model"}</h3>
            <p className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-muted/60 px-3 py-2 text-[13px] text-ink-body">{plan.prompt}</p>
            <p className="type-meta">Kept out: {plan.negative_prompt}</p>
          </div>
          {plan.notes.map((n) => <p key={n} className="type-meta">{n}</p>)}
        </div>
      </div>
    </section>
  );
}
