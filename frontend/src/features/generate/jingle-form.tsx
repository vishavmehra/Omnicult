"use client";

import { useState } from "react";

import { Field } from "@/components/forms/fields";
import type { Region } from "@/features/desk/types";
import { cn } from "@/lib/utils";

import { useStartJingle, type GenerateCapabilities, type JingleRequest } from "./api";
import { Group, StartRow, TargetFields } from "./form-parts";
import { Chip, INPUT } from "./parts";

const MAX_INSTRUMENTS = 5;

/** Setup for a jingle: region, mood, festival and instrument hints, a length; one Lyria call. */
export function JingleForm({
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
  const options = caps.jingle;
  const info = caps.generators.find((g) => g.kind === "jingle");
  const [region, setRegion] = useState(startRegion);
  const [mood, setMood] = useState(options.moods[0] ?? "Warm and joyful");
  const [festival, setFestival] = useState("");
  const [instruments, setInstruments] = useState<string[]>([]);
  const [seconds, setSeconds] = useState<JingleRequest["seconds"]>(15);
  const [confirmed, setConfirmed] = useState(false);
  const start = useStartJingle(campaignId);
  const blocked = mood.trim() ? null : "Choose or write a mood.";

  const toggle = (name: string) =>
    setInstruments((all) => (all.includes(name) ? all.filter((x) => x !== name) : all.length < MAX_INSTRUMENTS ? [...all, name] : all));

  function submit() {
    if (start.isPending || working) return; // a double click or a held Enter never sends a second paid call
    start.mutate(
      { region_code: region, mood: mood.trim(), festival: festival.trim() || null, instruments, seconds, confirm_cost: caps.mode === "live" && confirmed },
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
      aria-label="Generate a jingle"
    >
      <TargetFields regions={regions} region={region} language="" languages={[]} onRegion={setRegion} onLanguage={() => undefined} hideLanguage />

      <Group legend="Mood">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Mood">
          {options.moods.map((m) => (
            <Chip key={m} pressed={mood === m} onClick={() => setMood(m)}>
              {m}
            </Chip>
          ))}
        </div>
        <label htmlFor="gen-mood" className="sr-only">
          Or write the mood
        </label>
        <input id="gen-mood" className={INPUT} maxLength={120} value={mood} onChange={(e) => setMood(e.target.value)} placeholder="Or write your own" />
      </Group>

      <Field label="Festival" htmlFor="gen-festival" hint="A hint to the model, not a claim about the festival.">
        <input id="gen-festival" className={INPUT} maxLength={80} value={festival} onChange={(e) => setFestival(e.target.value)} placeholder="For example Deepavali" />
      </Field>
      {caps.brand.festival_hooks.length > 0 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Festivals in your brief">
          {caps.brand.festival_hooks.map((f) => (
            <Chip key={f} pressed={festival === f} onClick={() => setFestival(festival === f ? "" : f)}>
              {f}
            </Chip>
          ))}
        </div>
      )}

      <Group legend={`Instruments (up to ${MAX_INSTRUMENTS})`}>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Instruments">
          {options.instruments.map((name) => (
            <Chip key={name} pressed={instruments.includes(name)} onClick={() => toggle(name)} disabled={!instruments.includes(name) && instruments.length >= MAX_INSTRUMENTS}>
              {name}
            </Chip>
          ))}
        </div>
      </Group>

      <Group legend="Length" hint={`The model makes a ${options.clip_seconds} second clip. A shorter length is cut in code with a fade-out; it is still one clip.`}>
        <div className="inline-flex rounded-lg border border-border bg-surface p-0.5" role="group" aria-label="Length">
          {options.seconds.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={seconds === s}
              onClick={() => setSeconds(s as JingleRequest["seconds"])}
              className={cn(
                "h-8 rounded-md px-3.5 text-[13.5px] font-medium tabular-nums outline-none focus-visible:ring-3 focus-visible:ring-ring/30 max-sm:h-10",
                seconds === s ? "bg-surface-raised text-ink shadow-card" : "text-ink-secondary hover:text-ink",
              )}
            >
              {s} s
            </button>
          ))}
        </div>
      </Group>

      {start.isError && <p role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-[13.5px] text-ink">{start.error.message}</p>}
      <StartRow
        caps={caps}
        estimate={info?.estimated_cost_usd}
        what="one Lyria call"
        label="Generate jingle"
        confirmed={confirmed}
        onConfirm={setConfirmed}
        working={working || start.isPending}
        blocked={blocked}
        pending={start.isPending}
      />
    </form>
  );
}
