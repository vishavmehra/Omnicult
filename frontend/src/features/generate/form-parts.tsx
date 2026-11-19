"use client";

import { LoaderCircle, Sparkles } from "lucide-react";
import { useId, type ReactNode } from "react";

import { Field } from "@/components/forms/fields";
import { Button } from "@/components/ui/button";
import type { Region } from "@/features/desk/types";

import type { GenerateCapabilities } from "./api";
import { SELECT, usd } from "./parts";

export const SCRIPT_NAMES: Record<string, string> = {
  Deva: "Devanagari",
  Taml: "Tamil",
  Mlym: "Malayalam",
  Beng: "Bengali",
  Telu: "Telugu",
  Knda: "Kannada",
  Gujr: "Gujarati",
  Guru: "Gurmukhi",
  Orya: "Odia",
  Latn: "Latin",
};

type LanguageOption = { code: string; name: string; script: string };

/** The language a region speaks first, when the options include it. */
export function languageFor(region: Region | undefined, options: LanguageOption[], fallback = "en") {
  const wanted = region?.primary_language;
  return options.find((o) => o.code === wanted)?.code ?? options.find((o) => o.code === fallback)?.code ?? options[0]?.code ?? fallback;
}

/** Append an idea to a prompt once, joined with a comma. */
export function addIdea(text: string, idea: string) {
  const trimmed = text.trim();
  if (trimmed.toLowerCase().includes(idea.toLowerCase())) return text;
  return trimmed ? `${trimmed.replace(/[.,]$/, "")}, ${idea.toLowerCase()}` : idea;
}

/** Region and language, the two things every generator is aimed at. */
export function TargetFields({
  regions,
  region,
  language,
  languages,
  onRegion,
  onLanguage,
  hideLanguage,
}: {
  regions: Region[];
  region: string;
  language: string;
  languages: LanguageOption[];
  onRegion: (code: string) => void;
  onLanguage: (code: string) => void;
  hideLanguage?: boolean;
}) {
  const id = useId();
  return (
    <div className={hideLanguage ? "grid gap-3" : "grid gap-3 sm:grid-cols-2"}>
      <Field label="Region" htmlFor={`${id}-region`} required>
        <select id={`${id}-region`} className={SELECT} value={region} onChange={(e) => onRegion(e.target.value)}>
          {regions.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
        </select>
      </Field>
      {!hideLanguage && (
        <Field label="Language" htmlFor={`${id}-language`} required>
          <select id={`${id}-language`} className={SELECT} value={language} onChange={(e) => onLanguage(e.target.value)}>
            {languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name} · {SCRIPT_NAMES[l.script] ?? l.script}
              </option>
            ))}
          </select>
        </Field>
      )}
    </div>
  );
}

/** The estimate before anything runs, the confirmation a paid call needs, and the one primary action. Demo projects charge nothing. */
export function StartRow({
  caps,
  estimate,
  what,
  label,
  confirmed,
  onConfirm,
  working,
  blocked,
  pending,
}: {
  caps: GenerateCapabilities;
  estimate: number | null | undefined;
  what: string;
  label: string;
  confirmed: boolean;
  onConfirm: (next: boolean) => void;
  working: boolean;
  blocked: string | null;
  pending: boolean;
}) {
  const demo = caps.mode === "demo";
  const ready = !blocked && (demo || confirmed) && !working && !pending;
  return (
    <div className="space-y-3 border-t border-border pt-4 lg:sticky lg:bottom-0 lg:z-10 lg:-mx-5 lg:-mb-5 lg:bg-surface lg:px-5 lg:pb-5">
      {demo ? null : (
        <label className="flex items-start gap-2.5 text-[13.5px] text-ink-body">
          <input type="checkbox" checked={confirmed} onChange={(e) => onConfirm(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-primary" />
          <span>
            Run {what}. Estimated {usd(estimate)}, charged to the project; each call is made once and never retried by the app. The run stops
            at the ${caps.run_budget_usd.toFixed(2)} per-run ceiling.
          </span>
        </label>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={!ready} className="min-w-44">
          {pending || working ? <LoaderCircle aria-hidden className="animate-spin" /> : <Sparkles aria-hidden />}
          {working ? "Working…" : label}
        </Button>
        {blocked && <span className="text-[13px] text-ink-secondary">{blocked}</span>}
      </div>
    </div>
  );
}

/** A labelled group of chips or controls. */
export function Group({ legend, hint, children }: { legend: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 space-y-2">
      <legend className="text-[13px] font-medium text-ink">{legend}</legend>
      {children}
      {hint && <p className="max-w-prose text-xs text-ink-secondary">{hint}</p>}
    </fieldset>
  );
}
