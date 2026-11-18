"use client";

import { TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";

import { Field } from "@/components/forms/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useRemakeRun, useStartSound, useVersion, type RemakeCapabilities, type RemakeOutput, type VersionSummary } from "./api";
import { AiTag, CostConfirm, Notice, RunProgress, SELECT, SourceLine, mmss, usd } from "./parts";
import { defaultVoiceLines } from "./plan";

const SPEECH_LINE_ESTIMATE = 0.0012;
const GRID = (hasBack: boolean) => (hasBack ? "md:grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)]" : "md:grid-cols-[4.5rem_minmax(0,1fr)]");

/** Setup for a voice-over: which lines, which voice, an optional jingle, then run. */
export function SoundPanel({
  campaignId,
  demo,
  caps,
  versions,
  outputs,
}: {
  campaignId: string;
  demo: boolean;
  caps: RemakeCapabilities;
  versions: VersionSummary[];
  outputs: RemakeOutput[];
}) {
  const sounds = outputs.filter((o) => o.kind === "sound");
  const [versionId, setVersionId] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [voice, setVoice] = useState("Sulafat");
  const [jingle, setJingle] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [viewId, setViewId] = useState<string | null>(null);

  const version = versions.find((v) => v.id === versionId) ?? versions[versions.length - 1] ?? null;
  const detail = useVersion(campaignId, version?.id ?? null);
  const start = useStartSound(campaignId);
  const run = useRemakeRun(campaignId, runId);

  const candidates = detail.data ? defaultVoiceLines(detail.data.elements) : [];
  const selected = picked ?? candidates.map((e) => e.id);
  const chosen = candidates.filter((e) => selected.includes(e.id));
  const working = start.isPending || (run.data !== undefined && (run.data.status === "queued" || run.data.status === "running"));
  const speechOff = !demo && !caps.speech.configured;
  const jingleOff = !demo && !caps.music.configured;
  const hasTarget = Boolean(version?.region_code && version?.language);
  const estimate = chosen.length * (caps.speech.estimated_cost_usd ?? SPEECH_LINE_ESTIMATE) + (jingle ? (caps.music.estimated_cost_usd ?? 0) : 0);
  const blocked = !version
    ? "This campaign has no version yet."
    : !hasTarget
      ? "Choose a version that is already adapted to a region and language."
      : detail.data && chosen.length === 0
        ? "This version has no voiceover or caption line. Add one in Creative Studio."
        : chosen.length > caps.max_voice_lines
          ? `A run speaks at most ${caps.max_voice_lines} lines.`
          : null;
  const canRun = !blocked && !speechOff && (demo || confirmed) && !working && chosen.length > 0;
  const shown = sounds.find((o) => o.run_id === runId) ?? sounds.find((o) => o.id === viewId) ?? (runId ? undefined : sounds[0]);

  function submit() {
    if (!version?.region_code || !version.language) return;
    start.mutate(
      {
        version_id: version.id,
        region_code: version.region_code,
        language: version.language,
        element_ids: picked ? chosen.map((e) => e.id) : null,
        voice,
        jingle: jingle && !demo,
        confirm_cost: !demo && confirmed,
      },
      { onSuccess: (accepted) => { setRunId(accepted.run_id); setViewId(null); setConfirmed(false); } },
    );
  }

  if (!versions.length) {
    return <EmptyState title="No version to speak yet" description="Remake works on a version of the campaign. Create or open one in Creative Studio first." />;
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <form
        className="space-y-4 self-start rounded-card border border-border bg-surface p-4 shadow-card"
        onSubmit={(e) => { e.preventDefault(); submit(); }}
        aria-label="Remake: Sound setup"
      >
        <Field label="Version" htmlFor="rs-version" required>
          <select id="rs-version" className={SELECT} value={version?.id ?? ""} onChange={(e) => { setVersionId(e.target.value); setPicked(null); }}>
            {[...versions].reverse().map((v) => (
              <option key={v.id} value={v.id}>{v.label} · {v.region_code ?? "no region"} · {v.language ?? "no language"}</option>
            ))}
          </select>
        </Field>

        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-[13px] font-medium text-ink-secondary">Lines to speak</legend>
          {detail.isPending && <p className="type-meta">Loading lines…</p>}
          {candidates.map((e) => (
            <label key={e.id} className="flex items-start gap-2.5 rounded-lg border border-border px-2.5 py-2 text-[13.5px] has-[:checked]:bg-surface-muted">
              <input
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-primary"
                checked={selected.includes(e.id)}
                onChange={(ev) => setPicked(ev.target.checked ? candidates.filter((c) => c.id === e.id || selected.includes(c.id)).map((c) => c.id) : selected.filter((id) => id !== e.id))}
              />
              <span className="min-w-0">
                <span lang={e.language ?? undefined} className="block text-ink">{String(e.value)}</span>
                <span className="type-meta">{e.id}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <Field label="Voice" htmlFor="rs-voice">
          <select id="rs-voice" className={SELECT} value={voice} onChange={(e) => setVoice(e.target.value)}>
            {caps.voices.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </Field>

        <label className={cn("flex items-start gap-2.5 text-[13.5px] text-ink-body", (demo || jingleOff) && "opacity-60")}>
          <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-primary" checked={jingle && !demo} disabled={demo || jingleOff} onChange={(e) => setJingle(e.target.checked)} />
          <span>
            Also make a short instrumental jingle{demo ? "" : ` (${usd(caps.music.estimated_cost_usd)})`}
            {demo && <span className="type-meta block">Demo projects keep the existing music bed.</span>}
            {jingleOff && !demo && <span className="type-meta block">No music model is configured on this server.</span>}
          </span>
        </label>

        {speechOff && <Notice>No speech model is configured on this server, so Remake: Sound cannot run here.</Notice>}
        {blocked && !speechOff && <Notice tone="info">{blocked}</Notice>}
        <CostConfirm demo={demo} estimate={estimate} what={`${chosen.length} speech ${chosen.length === 1 ? "call" : "calls"}${jingle ? " and a jingle" : ""}`} checked={confirmed} onChange={setConfirmed} />
        <Button type="submit" disabled={!canRun} className="w-full">
          {working ? "Working…" : demo ? "Play the saved voice-over" : `Speak ${chosen.length} ${chosen.length === 1 ? "line" : "lines"}`}
        </Button>
        {start.error && <ErrorState error={start.error} />}
      </form>

      <div className="min-w-0 space-y-4">
        {runId && <RunProgress run={run.data} onRetry={submit} />}
        {shown ? (
          <SoundResult output={shown} />
        ) : runId && working ? (
          <LoadingState label="Speaking the lines…" />
        ) : !runId ? (
          <EmptyState title="No voice-over yet" description="Pick the lines and a voice. The player, the line-by-line script and its English back-translation appear here." />
        ) : null}
        {sounds.length > 1 && (
          <section aria-label="Earlier voice-overs" className="space-y-1.5">
            <h3 className="text-[13px] font-semibold text-ink-secondary">Earlier voice-overs</h3>
            <ul className="divide-y divide-border rounded-card border border-border bg-surface">
              {sounds.map((o) => (
                <li key={o.id}>
                  <button type="button" onClick={() => { setRunId(null); setViewId(o.id); }} aria-current={o.id === shown?.id ? "true" : undefined}
                    className={cn("flex w-full items-center justify-between gap-3 px-3.5 py-2 text-left text-[13px] hover:bg-surface-muted", o.id === shown?.id && "bg-surface-muted")}>
                    <span className="text-ink-body">{o.language} · {o.sound?.voice} · {formatDate(o.created_at)}</span>
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

/** The player and the script. Clicking a line seeks to it; the line being spoken is marked while it plays. */
function SoundResult({ output }: { output: RemakeOutput }) {
  const s = output.sound;
  const audio = useRef<HTMLAudioElement>(null);
  const [now, setNow] = useState(0);
  const src = useAssetObjectUrl(s ? { id: s.voiceover_asset_id, content_url: s.voiceover_url } : null);
  const jingle = useAssetObjectUrl(s?.jingle ? { id: s.jingle.asset_id, content_url: s.jingle.url } : null);
  if (!s) return <Notice>This remake has no voice-over.</Notice>;
  const hasBack = s.lines.some((l) => l.back_translation);
  const active = s.lines.findIndex((l) => l.duration_ms > 0 && now >= l.start_ms && now < l.end_ms);
  const seek = (ms: number) => {
    if (!audio.current) return;
    audio.current.currentTime = ms / 1000;
    void audio.current.play();
  };
  return (
    <section aria-label="Voice-over result" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold text-ink">Voice-over <AiTag /></h2>
        <SourceLine>
          {s.source === "demo_fixture" ? "Saved demonstration output" : s.model} · voice {s.voice} · {s.language_code} · {formatDate(output.created_at)}
          {s.source === "demo_fixture" ? "" : ` · ${usd(output.estimated_cost_usd)}`} · no native-speaker review
        </SourceLine>
      </div>

      <div className="space-y-2 rounded-card border border-border bg-surface p-3.5">
        {src ? (
          <audio ref={audio} src={src} controls preload="metadata" className="w-full" aria-label="Voice-over" onTimeUpdate={(e) => setNow(e.currentTarget.currentTime * 1000)} />
        ) : (
          <p className="type-meta">Loading audio…</p>
        )}
        <p className="type-meta">{mmss(s.total_duration_ms)} in total</p>
        {s.jingle && (
          <div className="space-y-1 border-t border-border pt-2">
            <p className="text-[13px] font-medium text-ink-secondary">Jingle · {s.jingle.model} · {mmss(s.jingle.duration_ms)}</p>
            {jingle ? <audio src={jingle} controls preload="metadata" className="w-full" aria-label="Jingle" /> : <p className="type-meta">Loading audio…</p>}
          </div>
        )}
      </div>

      <section aria-label="Line by line" className="rounded-card border border-border bg-surface">
        <div className={cn("hidden gap-4 border-b border-border px-3.5 py-2 text-[12.5px] font-medium text-ink-secondary md:grid", GRID(hasBack))}>
          <span>Time</span>
          <span>Script</span>
          {hasBack && <span className="flex items-center gap-2">English back-translation <AiTag>Model interpretation</AiTag></span>}
        </div>
        {!hasBack && <p className="border-b border-border px-3.5 py-2 text-[12.5px] text-ink-muted">No English back-translation is recorded for these lines. Transcreate them in Creative Studio to get one.</p>}
        <ol className="divide-y divide-border">
          {s.lines.map((l, i) => (
            <li key={l.element_id} aria-current={i === active ? "true" : undefined} className={cn("px-3.5 py-2.5", i === active && "bg-surface-muted")}>
              <div className={cn("grid gap-x-4 gap-y-1", GRID(hasBack))}>
                <button type="button" disabled={l.duration_ms === 0} onClick={() => seek(l.start_ms)} className="type-ledger w-fit text-left text-[13px] text-primary underline underline-offset-2 disabled:text-ink-muted disabled:no-underline" aria-label={`Play from ${mmss(l.start_ms)}`}>
                  {l.duration_ms ? mmss(l.start_ms) : "not spoken"}
                </button>
                <p lang={l.language} className="text-[14.5px] text-ink">{l.text}</p>
                {hasBack && <p className={cn("text-[13.5px]", l.back_translation ? "text-ink-body" : "text-ink-muted")}>{l.back_translation ?? "No back-translation recorded."}</p>}
              </div>
              <p className="type-meta mt-1 md:pl-[5.5rem]">
                {l.element_id}{l.duration_ms ? ` · ${(l.duration_ms / 1000).toFixed(1)} s` : ""}
                {l.window_ms != null && l.duration_ms ? ` · scene ${(l.window_ms / 1000).toFixed(1)} s` : ""}
              </p>
              {l.problems.map((p) => (
                <p key={p} className="mt-1 flex items-start gap-1.5 text-[12.5px] text-warning md:pl-[5.5rem]"><TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />{p}</p>
              ))}
            </li>
          ))}
        </ol>
      </section>

      <details className="rounded-card border border-border bg-surface px-3.5 py-2.5 text-[13px] text-ink-body">
        <summary className="cursor-pointer font-medium text-ink">Provenance</summary>
        <dl className="mt-2.5 grid gap-1.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="type-meta">Prompt version</dt><dd className="font-mono text-[12.5px]">{output.prompt_version}</dd>
          <dt className="type-meta">Version created</dt><dd className="font-mono text-[12.5px]">{output.result_version_id}</dd>
          <dt className="type-meta">Run</dt><dd className="font-mono text-[12.5px]">{output.run_id ?? "none"}</dd>
          {output.limitations.length > 0 && (<><dt className="type-meta">Notes</dt><dd><ul className="list-disc space-y-1 pl-4">{output.limitations.map((n) => <li key={n}>{n}</li>)}</ul></dd></>)}
        </dl>
      </details>
    </section>
  );
}
