"use client";

import { Plus, Quote, X } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Region } from "@/features/desk/types";
import { cn } from "@/lib/utils";

import { useStartVoice, useVersion, useVersionList, type GenerateCapabilities, type Pace } from "./api";
import { Group, languageFor, StartRow, TargetFields } from "./form-parts";
import { Chip, SELECT, TEXTAREA } from "./parts";

type Line = { key: number; text: string; elementId: string | null };
const TEXT_KINDS = new Set(["voiceover", "caption", "cta", "headline", "tagline", "body"]);
const PACE_LABEL: Record<Pace, string> = { slow: "Slower", normal: "As spoken", brisk: "Brisker" };
let nextKey = 1;
const fresh = (text = "", elementId: string | null = null): Line => ({ key: nextKey++, text, elementId });

/** Setup for a voice-over: the lines, the language, a voice and a pace; every line is one speech call. */
export function VoiceForm({
  campaignId,
  caps,
  regions,
  startRegion,
  working,
  onStarted,
}: {
  campaignId: string;
  caps: GenerateCapabilities;
  regions: Region[];
  startRegion: string;
  working: boolean;
  onStarted: (runId: string) => void;
}) {
  const options = caps.voice;
  const info = caps.generators.find((g) => g.kind === "voice");
  const demo = caps.mode === "demo";
  const [region, setRegion] = useState(startRegion);
  const [language, setLanguage] = useState(() => languageFor(regions.find((r) => r.code === startRegion), options.languages, "ta"));
  const [lines, setLines] = useState<Line[]>(() => (demo ? options.sample_lines.map((t) => fresh(t)) : [fresh()]));
  const [voice, setVoice] = useState(options.voices[0]?.name ?? "Sulafat");
  const [pace, setPace] = useState<Pace>("normal");
  const [confirmed, setConfirmed] = useState(false);
  const [versionId, setVersionId] = useState<string | null>(null);
  const versions = useVersionList(campaignId);
  const version = useVersion(campaignId, versionId);
  const start = useStartVoice(campaignId);
  const pickId = useId();

  const filled = lines.filter((l) => l.text.trim());
  const estimate = (info?.estimated_cost_usd ?? 0) * filled.length;
  const blocked = filled.length === 0 ? "Write at least one line." : filled.length > options.max_lines ? `At most ${options.max_lines} lines.` : null;
  const pickable = (version.data?.elements ?? []).filter((e) => TEXT_KINDS.has(e.kind) && typeof e.value === "string" && e.value.trim());

  const update = (key: number, patch: Partial<Line>) => setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  function submit() {
    if (start.isPending || working) return; // a double click or a held Enter never sends a second paid call
    start.mutate(
      {
        region_code: region,
        language,
        voice,
        pace: options.pace_supported ? pace : "normal",
        lines: filled.map((l) => ({ text: l.text.trim(), element_id: l.elementId })),
        confirm_cost: !demo && confirmed,
      },
      {
        onSuccess: (accepted) => {
          onStarted(accepted.run_id);
          setConfirmed(false);
        },
      },
    );
  }

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      aria-label="Generate a voice-over"
    >
      <TargetFields
        regions={regions}
        region={region}
        language={language}
        languages={options.languages}
        onRegion={(code) => {
          setRegion(code);
          setLanguage(languageFor(regions.find((r) => r.code === code), options.languages, language));
        }}
        onLanguage={setLanguage}
      />

      <Group legend="Script, one line at a time" hint="Each line is spoken on its own and the lines are joined into one track, so you can hear every line by itself afterwards.">
        <ol className="space-y-2">
          {lines.map((line, index) => (
            <li key={line.key} className="flex items-start gap-2">
              <span aria-hidden className="type-meta mt-2.5 w-5 shrink-0 text-right tabular-nums">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <label htmlFor={`gen-line-${line.key}`} className="sr-only">
                  Line {index + 1}
                </label>
                <textarea
                  id={`gen-line-${line.key}`}
                  lang={language}
                  rows={2}
                  maxLength={options.max_line_chars}
                  value={line.text}
                  onChange={(e) => update(line.key, { text: e.target.value, elementId: line.elementId && e.target.value === line.text ? line.elementId : null })}
                  className={TEXTAREA}
                  placeholder={index === 0 ? "The line to speak" : "Another line"}
                />
              </div>
              <button
                type="button"
                onClick={() => setLines((all) => (all.length > 1 ? all.filter((l) => l.key !== line.key) : [fresh()]))}
                aria-label={`Remove line ${index + 1}`}
                className="mt-1 grid size-9 shrink-0 place-items-center rounded-lg text-ink-secondary outline-none hover:bg-surface-muted hover:text-ink focus-visible:ring-3 focus-visible:ring-ring/30 max-sm:size-11"
              >
                <X aria-hidden className="size-4" />
              </button>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" disabled={lines.length >= options.max_lines} onClick={() => setLines((all) => [...all, fresh()])}>
            <Plus aria-hidden />
            Add a line
          </Button>
          {options.sample_lines.length > 0 && (
            <Button type="button" variant="outline" size="sm" onClick={() => setLines(options.sample_lines.map((t) => fresh(t)))}>
              <Quote aria-hidden />
              Use the suggested lines
            </Button>
          )}
        </div>
      </Group>

      {(versions.data?.length ?? 0) > 0 && (
        <Group legend="Pull copy from a Studio version" hint="A line from a version keeps its link, so its English back-translation shows beside it when a transcreation recorded one.">
          <label htmlFor={pickId} className="sr-only">
            Studio version
          </label>
          <select id={pickId} className={SELECT} value={versionId ?? ""} onChange={(e) => setVersionId(e.target.value || null)}>
            <option value="">Choose a version</option>
            {[...(versions.data ?? [])].reverse().map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} · {v.region_code ?? "no region"} · {v.language ?? "no language"}
              </option>
            ))}
          </select>
          {versionId && pickable.length === 0 && !version.isPending && <p className="text-[13px] text-ink-secondary">This version has no line of copy.</p>}
          <ul className="space-y-1">
            {pickable.map((e) => (
              <li key={e.id} className="flex items-start gap-2 rounded-lg border border-border px-2.5 py-1.5 text-[13.5px]">
                <span lang={e.language ?? undefined} className="min-w-0 flex-1 text-ink">
                  {String(e.value)}
                  <span className="type-meta block">{e.kind}</span>
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  disabled={lines.length >= options.max_lines && !lines.every((l) => !l.text.trim())}
                  onClick={() =>
                    setLines((all) => {
                      const empty = all.length === 1 && !all[0].text.trim();
                      return empty ? [fresh(String(e.value), e.id)] : [...all, fresh(String(e.value), e.id)];
                    })
                  }
                >
                  Add
                </Button>
              </li>
            ))}
          </ul>
        </Group>
      )}

      <Group legend="Voice" hint="Style labels are the ones in Google's published voice list.">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Voice">
          {options.voices.map((v) => (
            <Chip key={v.name} pressed={voice === v.name} onClick={() => setVoice(v.name)}>
              {v.name}
              {v.style && <span className="text-ink-secondary">{v.style}</span>}
            </Chip>
          ))}
        </div>
      </Group>

      {options.pace_supported && (
        <Group legend="Pace" hint="Changed in code after the speech is made, so the pitch stays and no extra call is made.">
          <div className="inline-flex rounded-lg border border-border bg-surface p-0.5" role="group" aria-label="Pace">
            {options.paces.map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={pace === p}
                onClick={() => setPace(p)}
                className={cn(
                  "h-8 rounded-md px-3 text-[13.5px] font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/30 max-sm:h-10",
                  pace === p ? "bg-surface-raised text-ink shadow-card" : "text-ink-secondary hover:text-ink",
                )}
              >
                {PACE_LABEL[p]}
              </button>
            ))}
          </div>
        </Group>
      )}

      {start.isError && <p role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-[13.5px] text-ink">{start.error.message}</p>}
      <StartRow
        caps={caps}
        estimate={estimate}
        what={`${filled.length || 1} speech call${filled.length > 1 ? "s" : ""}`}
        label="Generate voice-over"
        confirmed={confirmed}
        onConfirm={setConfirmed}
        working={working || start.isPending}
        blocked={blocked}
        pending={start.isPending}
      />
    </form>
  );
}
