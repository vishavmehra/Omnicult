"use client";

import { Search } from "lucide-react";
import { useId, useMemo, useState, type FormEvent } from "react";

import { Field } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { serverFieldErrors } from "@/features/atlas/form-errors";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { useSaveBrief } from "./api";
import { Group, Lines, Repeater, Select, ServerProblems, ToggleChip } from "./form-parts";
import {
  AGE_BANDS,
  CITY_TIERS,
  STATUS_LABEL,
  languageName,
  scriptName,
  slugify,
  uniqueSlug,
  type Brief,
  type BriefContent,
  type Region,
} from "./types";

type Channel = BriefContent["channels"][number];
type Moment = NonNullable<BriefContent["dates"]>["key_moments"][number];
type DateSource = NonNullable<BriefContent["dates"]>["sources"][number];

const blank = (s: string | null | undefined) => !s || !s.trim();
const text = (s: string | null | undefined) => (blank(s) ? null : s!.trim());

/** A number input that keeps what you type ("1.", "") and reports a number only when there is one. */
function NumberInput({ id, value, onChange, min = 0, step, placeholder, "aria-label": label }: { id?: string; value: number | null | undefined; onChange(next: number | null): void; min?: number; step?: number | "any"; placeholder?: string; "aria-label"?: string }) {
  const [raw, setRaw] = useState(value === null || value === undefined ? "" : String(value));
  return (
    <Input
      id={id}
      aria-label={label}
      type="number"
      inputMode="decimal"
      min={min}
      step={step ?? "any"}
      placeholder={placeholder}
      value={raw}
      className="bg-surface tabular-nums"
      onChange={(e) => {
        setRaw(e.target.value);
        const n = e.target.value.trim() === "" ? null : Number(e.target.value);
        onChange(n === null || Number.isFinite(n) ? n : null);
      }}
    />
  );
}

/** The id a name should carry: the stored one while the name still reads the same, a fresh slug once it changes. */
const SLUG = /^[a-z0-9][a-z0-9_.-]{0,63}$/;
const idFromName = (name: string, current: string, taken: string[]) => {
  const same = current && SLUG.test(current) && slugify(name) === slugify(current.replace(/[_-]/g, " "));
  return same ? current : uniqueSlug(name, taken, "item");
};

/** Empty strings become nulls and empty groups disappear, so a half-filled form never sends noise. */
export function cleanBrief(d: BriefContent): BriefContent {
  const product = d.product && !blank(d.product.name) ? { ...d.product, name: d.product.name.trim(), description: text(d.product.description), price_note: text(d.product.price_note), price: d.product.price && d.product.price.amount !== null ? d.product.price : null } : null;
  const aud = d.target_audience;
  const audience = aud && (!blank(aud.summary) || aud.age_bands.length || aud.city_tiers.length || !blank(aud.targeting_exclusions)) ? { ...aud, summary: text(aud.summary), targeting_exclusions: text(aud.targeting_exclusions) } : null;
  const channelIds: string[] = [];
  const channels = d.channels
    .filter((c) => !blank(c.name))
    .map((c) => {
      const id = idFromName(c.name, c.id, channelIds);
      channelIds.push(id);
      return { ...c, id, name: c.name.trim(), format: text(c.format), creative_ref: text(c.creative_ref) };
    });
  const budget = d.budget && d.budget.total !== null && d.budget.total !== undefined && !blank(d.budget.currency) ? { ...d.budget, currency: d.budget.currency.trim().toUpperCase(), note: text(d.budget.note) } : null;
  let dates = null as BriefContent["dates"];
  if (d.dates && !blank(d.dates.start) && !blank(d.dates.end)) {
    const sourceIds: string[] = [];
    const sources = d.dates.sources
      .filter((s) => !blank(s.title))
      .map((s) => {
        const id = idFromName(s.title, s.id, sourceIds);
        sourceIds.push(id);
        return { ...s, id, title: s.title.trim(), publisher: text(s.publisher), url: text(s.url), retrieved_at: text(s.retrieved_at) };
      });
    const momentIds: string[] = [];
    const key_moments = d.dates.key_moments
      .filter((m) => !blank(m.name) && !blank(m.date))
      .map((m) => {
        const id = idFromName(m.name, m.id, momentIds);
        momentIds.push(id);
        return { ...m, id, name: m.name.trim(), note: text(m.note), source_ids: m.source_ids.filter((s) => sources.some((x) => x.id === s)) };
      });
    dates = { ...d.dates, timezone: text(d.dates.timezone) ?? "Asia/Kolkata", note: text(d.dates.note), sources, key_moments };
  }
  let success_metric = null as BriefContent["success_metric"];
  if (d.success_metric && !blank(d.success_metric.primary.definition)) {
    const taken: string[] = [];
    const metric = (m: { id: string; definition: string; target: string | null }, fallback: string) => {
      const id = idFromName(blank(m.id) ? m.definition.split(/\s+/).slice(0, 4).join(" ") : m.id.replace(/[_-]/g, " "), m.id, taken) || fallback;
      taken.push(id);
      return { id, definition: m.definition.trim(), target: text(m.target) };
    };
    success_metric = {
      primary: metric(d.success_metric.primary, "primary"),
      secondary: d.success_metric.secondary.filter((m) => !blank(m.definition)).map((m) => metric(m, "secondary")),
      note: text(d.success_metric.note),
    };
  }
  const c = d.cta;
  const original = c?.original && !blank(c.original.text) ? { ...c.original, text: c.original.text.trim(), translation_en: text(c.original.translation_en) } : null;
  const cta = c && (!blank(c.text_en) || !blank(c.festival_hook) || original) ? { text_en: text(c.text_en), festival_hook: text(c.festival_hook), original } : null;
  return {
    ...d,
    objective: text(d.objective),
    primary_message: text(d.primary_message),
    product,
    target_audience: audience,
    channels,
    budget,
    dates,
    success_metric,
    cta,
    constraints: d.constraints.map((x) => x.trim()).filter(Boolean),
  };
}

/** Filterable checklist of states and union territories. */
function RegionChecklist({ regions, selected, disabledCode, onToggle }: { regions: Region[]; selected: string[]; disabledCode: string | null; onToggle(code: string): void }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = regions.filter((r) => !q || r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q));
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-muted" />
        <Input aria-label="Filter regions" placeholder="Filter states and union territories" value={query} onChange={(e) => setQuery(e.target.value)} className="bg-surface pl-8" />
      </div>
      <ul className="clay-well grid max-h-56 gap-px overflow-y-auto rounded-xl p-1.5 sm:grid-cols-2">
        {shown.map((r) => (
          <li key={r.code}>
            <label className={cn("flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-[13.5px] has-focus-visible:outline-2 has-focus-visible:outline-ring", r.code === disabledCode ? "cursor-not-allowed text-ink-muted" : "text-ink-body hover:bg-surface-muted/70")}>
              <input type="checkbox" checked={selected.includes(r.code)} disabled={r.code === disabledCode} onChange={() => onToggle(r.code)} className="size-4 accent-[var(--ember)]" />
              <span className="min-w-0 flex-1 truncate">{r.name}</span>
              <span className="font-mono text-[11px] text-ink-muted">{r.code}</span>
            </label>
          </li>
        ))}
        {shown.length === 0 && <li className="px-2 py-2 text-[13px] text-ink-muted">No region matches.</li>}
      </ul>
    </div>
  );
}

/**
 * Edit the brief. The whole brief is replaced; a changed brief becomes the next version, an unchanged one adds nothing.
 * Scripts follow from the chosen languages (each language has one script), so they cannot disagree.
 */
export function BriefEditor({ brief, initial, regions, onCancel, onSaved }: { brief: Brief; initial: BriefContent; regions: Region[]; onCancel(): void; onSaved(saved: Brief): void }) {
  const uid = useId();
  const id = (name: string) => `${uid}-${name}`;
  const [draft, setDraft] = useState<BriefContent>(() => structuredClone(initial));
  const [note, setNote] = useState("");
  const save = useSaveBrief(brief.campaign_id);
  const errors = serverFieldErrors(save.error);
  const stale = save.error instanceof ApiError && save.error.code === "CONFLICT";

  const set = (patch: Partial<BriefContent>) => setDraft((d) => ({ ...d, ...patch }));
  const byCode = useMemo(() => new Map(regions.map((r) => [r.code, r])), [regions]);
  const scriptOf = useMemo(() => {
    const m = new Map<string, string>([["en", "Latn"]]);
    regions.forEach((r) => r.languages.forEach((l) => m.set(l.code, l.script)));
    return m;
  }, [regions]);
  const everyLanguage = useMemo(() => [...scriptOf.keys()].sort((a, b) => languageName(a).localeCompare(languageName(b))), [scriptOf]);
  const nameOf = (code: string) => byCode.get(code)?.name ?? code;
  const inBrief = [...(draft.regions.origin ? [draft.regions.origin] : []), ...draft.regions.targets];

  function setRegions(origin: string | null, targets: string[]) {
    const keep = new Set([...(origin ? [origin] : []), ...targets]);
    setDraft((d) => {
      const languages = Object.fromEntries(Object.entries(d.languages).filter(([k]) => keep.has(k)));
      const scripts = Object.fromEntries(Object.entries(d.scripts).filter(([k]) => keep.has(k)));
      for (const code of keep) {
        if (languages[code]) continue;
        const region = byCode.get(code);
        const langs = [...new Set([region?.primary_language ?? "en", "en"])];
        languages[code] = langs;
        scripts[code] = [...new Set(langs.map((l) => scriptOf.get(l) ?? "Latn"))];
      }
      return {
        ...d,
        regions: { origin, targets },
        languages,
        scripts,
        budget: d.budget && { ...d.budget, by_region: Object.fromEntries(Object.entries(d.budget.by_region).filter(([k]) => keep.has(k))) },
        dates: d.dates && { ...d.dates, key_moments: d.dates.key_moments.map((m) => ({ ...m, region_codes: m.region_codes.filter((r) => keep.has(r)) })) },
        cta: d.cta && { ...d.cta, original: d.cta.original && (keep.has(d.cta.original.region_code) ? d.cta.original : { ...d.cta.original, region_code: origin ?? targets[0] ?? d.cta.original.region_code }) },
      };
    });
  }

  function toggleLanguage(code: string, lang: string) {
    setDraft((d) => {
      const current = d.languages[code] ?? [];
      const next = current.includes(lang) ? current.filter((l) => l !== lang) : [...current, lang];
      const languages = { ...d.languages };
      const scripts = { ...d.scripts };
      if (next.length) {
        languages[code] = next;
        scripts[code] = [...new Set(next.map((l) => scriptOf.get(l) ?? "Latn"))];
      } else {
        delete languages[code];
        delete scripts[code];
      }
      return { ...d, languages, scripts };
    });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (save.isPending) return;
    save.mutate({ content: cleanBrief(draft), changeNote: text(note), expectedVersion: brief.version }, { onSuccess: onSaved });
  }

  const budget = draft.budget;
  const dates = draft.dates;
  const metric = draft.success_metric;
  const cta = draft.cta;

  return (
    <form onSubmit={submit} className="space-y-5" aria-label="Edit the campaign brief">
      <Group legend="Objective" hint="What the campaign should achieve. It is also written to the campaign record, which other workspaces read.">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
          <Field label="Objective" htmlFor={id("objective")} hint={`${(draft.objective ?? "").length}/300`}>
            <Textarea id={id("objective")} rows={3} maxLength={300} value={draft.objective ?? ""} onChange={(e) => set({ objective: e.target.value })} className="bg-surface" />
          </Field>
          <Field label="Status" htmlFor={id("status")} required>
            <Select id={id("status")} value={draft.status} onChange={(v) => set({ status: v as BriefContent["status"] })}>
              {Object.entries(STATUS_LABEL).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Primary message" htmlFor={id("message")}>
          <Textarea id={id("message")} rows={2} value={draft.primary_message ?? ""} onChange={(e) => set({ primary_message: e.target.value })} className="bg-surface" />
        </Field>
      </Group>

      <Group legend="Product and audience">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Product name" htmlFor={id("p-name")}>
            <Input id={id("p-name")} value={draft.product?.name ?? ""} onChange={(e) => set({ product: { ...(draft.product ?? { description: null, net_weight_g: null, price: null, price_note: null }), name: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Net weight (grams)" htmlFor={id("p-weight")}>
            <NumberInput id={id("p-weight")} min={1} step={1} value={draft.product?.net_weight_g} onChange={(n) => set({ product: draft.product && { ...draft.product, net_weight_g: n } })} />
          </Field>
          <Field label="Description" htmlFor={id("p-desc")} className="sm:col-span-2">
            <Textarea id={id("p-desc")} rows={2} value={draft.product?.description ?? ""} onChange={(e) => set({ product: draft.product && { ...draft.product, description: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Price currency" htmlFor={id("p-cur")}>
            <Input id={id("p-cur")} maxLength={3} placeholder="INR" value={draft.product?.price?.currency ?? ""} onChange={(e) => set({ product: draft.product && { ...draft.product, price: { currency: e.target.value.toUpperCase(), amount: draft.product.price?.amount ?? 0 } } })} className="bg-surface uppercase" />
          </Field>
          <Field label="Price" htmlFor={id("p-price")}>
            <NumberInput id={id("p-price")} value={draft.product?.price?.amount} onChange={(n) => set({ product: draft.product && { ...draft.product, price: n === null ? null : { currency: draft.product.price?.currency || "INR", amount: n } } })} />
          </Field>
        </div>
        <Field label="Audience" htmlFor={id("a-summary")}>
          <Textarea id={id("a-summary")} rows={2} value={draft.target_audience?.summary ?? ""} onChange={(e) => set({ target_audience: { age_bands: [], city_tiers: [], targeting_exclusions: null, ...draft.target_audience, summary: e.target.value } })} className="bg-surface" />
        </Field>
        <div className="space-y-1.5">
          <p className="text-[13px] font-medium text-ink">
            Age bands <span className="font-normal text-ink-secondary">(optional)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {AGE_BANDS.map((b) => (
              <ToggleChip key={b} pressed={draft.target_audience?.age_bands.includes(b) ?? false} onClick={() => {
                const cur = draft.target_audience?.age_bands ?? [];
                set({ target_audience: { summary: null, city_tiers: [], targeting_exclusions: null, ...draft.target_audience, age_bands: cur.includes(b) ? cur.filter((x) => x !== b) : [...cur, b] } });
              }}>
                {b}
              </ToggleChip>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <p className="text-[13px] font-medium text-ink">
            City tiers <span className="font-normal text-ink-secondary">(optional)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {CITY_TIERS.map((t) => (
              <ToggleChip key={t.value} pressed={draft.target_audience?.city_tiers.includes(t.value) ?? false} onClick={() => {
                const cur = draft.target_audience?.city_tiers ?? [];
                set({ target_audience: { summary: null, age_bands: [], targeting_exclusions: null, ...draft.target_audience, city_tiers: cur.includes(t.value) ? cur.filter((x) => x !== t.value) : [...cur, t.value] } });
              }}>
                {t.label}
              </ToggleChip>
            ))}
          </div>
        </div>
        <Field label="Never targeted or sampled by" htmlFor={id("a-excl")} hint="For example religion, caste or other protected traits.">
          <Input id={id("a-excl")} value={draft.target_audience?.targeting_exclusions ?? ""} onChange={(e) => set({ target_audience: { summary: null, age_bands: [], city_tiers: [], ...draft.target_audience, targeting_exclusions: e.target.value } })} className="bg-surface" />
        </Field>
      </Group>

      <Group legend="Regions, languages and scripts" hint="Pick where the original was made and where it will run. Scripts follow from the languages you choose.">
        <Field label="Origin region" htmlFor={id("origin")} hint="Where the original creative was made.">
          <Select id={id("origin")} value={draft.regions.origin ?? ""} onChange={(v) => setRegions(v || null, draft.regions.targets.filter((t) => t !== v))}>
            <option value="">No origin region</option>
            {regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name} ({r.code})
              </option>
            ))}
          </Select>
        </Field>
        <div className="space-y-1.5">
          <p id={id("targets-label")} className="text-[13px] font-medium text-ink">
            Target regions <span className="font-normal text-ink-secondary">({draft.regions.targets.length} selected)</span>
          </p>
          <RegionChecklist
            regions={regions}
            selected={draft.regions.targets}
            disabledCode={draft.regions.origin}
            onToggle={(code) => setRegions(draft.regions.origin, draft.regions.targets.includes(code) ? draft.regions.targets.filter((t) => t !== code) : [...draft.regions.targets, code])}
          />
        </div>
        {inBrief.length > 0 && (
          <div className="space-y-2.5">
            <p className="text-[13px] font-medium text-ink">Languages per region</p>
            <ul className="space-y-2.5">
              {inBrief.map((code) => {
                const region = byCode.get(code);
                const offered = [...new Set([...(region?.languages.map((l) => l.code) ?? []), "en", ...(draft.languages[code] ?? [])])];
                const chosen = draft.languages[code] ?? [];
                const more = everyLanguage.filter((l) => !offered.includes(l));
                return (
                  <li key={code} className="space-y-1.5 rounded-lg border border-border bg-surface-muted/60 p-3">
                    <p className="text-[13.5px] font-medium text-ink">
                      {nameOf(code)} <span className="font-mono text-[11px] font-normal text-ink-muted">{code}{code === draft.regions.origin ? " · origin" : ""}</span>
                    </p>
                    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Languages for ${nameOf(code)}`}>
                      {offered.map((l) => (
                        <ToggleChip key={l} pressed={chosen.includes(l)} onClick={() => toggleLanguage(code, l)} title={scriptName(scriptOf.get(l) ?? "Latn")}>
                          {languageName(l)}
                        </ToggleChip>
                      ))}
                      {more.length > 0 && (
                        <Select label={`Add another language for ${nameOf(code)}`} value="" onChange={(v) => v && toggleLanguage(code, v)} className="w-44">
                          <option value="">Add a language</option>
                          {more.map((l) => (
                            <option key={l} value={l}>
                              {languageName(l)}
                            </option>
                          ))}
                        </Select>
                      )}
                    </div>
                    <p className="text-[12px] text-ink-muted">
                      Scripts: {draft.scripts[code]?.length ? draft.scripts[code]!.map(scriptName).join(", ") : "none until a language is chosen"}
                    </p>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Group>

      <Group legend="Channels">
        <Repeater<Channel>
          items={draft.channels}
          onChange={(channels) => set({ channels })}
          make={() => ({ id: "", name: "", format: null, creative_ref: null })}
          addLabel="Add a channel"
          noun="channel"
          max={20}
          empty="No channels yet."
          render={(c, setC, i) => (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Channel" htmlFor={id(`ch-${i}-name`)} required>
                <Input id={id(`ch-${i}-name`)} value={c.name} onChange={(e) => setC({ name: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Format" htmlFor={id(`ch-${i}-format`)}>
                <Input id={id(`ch-${i}-format`)} value={c.format ?? ""} onChange={(e) => setC({ format: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Creative reference" htmlFor={id(`ch-${i}-ref`)}>
                <Input id={id(`ch-${i}-ref`)} value={c.creative_ref ?? ""} onChange={(e) => setC({ creative_ref: e.target.value })} className="bg-surface font-mono text-[12px]" />
              </Field>
            </div>
          )}
        />
      </Group>

      <Group legend="Budget" hint="Planning numbers.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Currency" htmlFor={id("b-cur")} required>
            <Input id={id("b-cur")} maxLength={3} placeholder="INR" value={budget?.currency ?? ""} onChange={(e) => set({ budget: { total: null as unknown as number, by_region: {}, sample: false, note: null, ...budget, currency: e.target.value.toUpperCase() } }) /* a null total means "not entered"; cleanBrief drops the budget */} className="bg-surface uppercase" />
          </Field>
          <Field label="Total" htmlFor={id("b-total")} required>
            <NumberInput id={id("b-total")} value={budget?.total} onChange={(n) => set({ budget: { currency: budget?.currency || "INR", by_region: {}, sample: false, note: null, ...budget, total: n as number } })} />
          </Field>
        </div>
        {budget && inBrief.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[13px] font-medium text-ink">
              By region <span className="font-normal text-ink-secondary">(together at most the total)</span>
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {inBrief.map((code) => (
                <div key={code} className="flex items-center gap-2">
                  <label htmlFor={id(`b-${code}`)} className="w-32 shrink-0 truncate text-[13px] text-ink-body">
                    {nameOf(code)}
                  </label>
                  <NumberInput id={id(`b-${code}`)} value={budget.by_region[code]} onChange={(n) => {
                    const by = { ...budget.by_region };
                    if (n === null) delete by[code];
                    else by[code] = n;
                    set({ budget: { ...budget, by_region: by } });
                  }} />
                </div>
              ))}
            </div>
          </div>
        )}
        {budget && (
          <Field label="Note" htmlFor={id("b-note")}>
            <Input id={id("b-note")} value={budget.note ?? ""} onChange={(e) => set({ budget: { ...budget, note: e.target.value } })} className="bg-surface" />
          </Field>
        )}
      </Group>

      <Group legend="Campaign dates">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Start" htmlFor={id("d-start")} required>
            <Input id={id("d-start")} type="date" value={dates?.start ?? ""} onChange={(e) => set({ dates: { end: "", timezone: "Asia/Kolkata", key_moments: [], sources: [], note: null, ...dates, start: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="End" htmlFor={id("d-end")} required>
            <Input id={id("d-end")} type="date" min={dates?.start || undefined} value={dates?.end ?? ""} onChange={(e) => set({ dates: { start: "", timezone: "Asia/Kolkata", key_moments: [], sources: [], note: null, ...dates, end: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Timezone" htmlFor={id("d-tz")} hint="IANA name, for example Asia/Kolkata.">
            <Input id={id("d-tz")} value={dates?.timezone ?? "Asia/Kolkata"} onChange={(e) => set({ dates: { start: "", end: "", key_moments: [], sources: [], note: null, ...dates, timezone: e.target.value } })} className="bg-surface" />
          </Field>
        </div>
        {dates && (
          <>
            <div className="space-y-2">
              <p className="text-[13px] font-medium text-ink">Date sources</p>
              <Repeater<DateSource>
                items={dates.sources}
                onChange={(sources) => set({ dates: { ...dates, sources } })}
                make={() => ({ id: "", title: "", publisher: null, url: null, retrieved_at: null })}
                addLabel="Add a source"
                noun="source"
                max={30}
                empty="No sources. Key moments can cite a source once one is added."
                render={(s, setS, i) => (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Title" htmlFor={id(`s-${i}-t`)} required className="sm:col-span-2">
                      <Input id={id(`s-${i}-t`)} value={s.title} onChange={(e) => setS({ title: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Publisher" htmlFor={id(`s-${i}-p`)}>
                      <Input id={id(`s-${i}-p`)} value={s.publisher ?? ""} onChange={(e) => setS({ publisher: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Retrieved" htmlFor={id(`s-${i}-r`)}>
                      <Input id={id(`s-${i}-r`)} type="date" value={s.retrieved_at ?? ""} onChange={(e) => setS({ retrieved_at: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Link" htmlFor={id(`s-${i}-u`)} hint="Must start with http:// or https://" className="sm:col-span-2">
                      <Input id={id(`s-${i}-u`)} type="url" value={s.url ?? ""} onChange={(e) => setS({ url: e.target.value })} className="bg-surface" />
                    </Field>
                  </div>
                )}
              />
            </div>
            <div className="space-y-2">
              <p className="text-[13px] font-medium text-ink">Key moments</p>
              <Repeater<Moment>
                items={dates.key_moments}
                onChange={(key_moments) => set({ dates: { ...dates, key_moments } })}
                make={() => ({ id: "", name: "", date: "", region_codes: [], source_ids: [], note: null })}
                addLabel="Add a key moment"
                noun="key moment"
                max={30}
                empty="No key moments."
                render={(m, setM, i) => (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Moment" htmlFor={id(`m-${i}-n`)} required>
                      <Input id={id(`m-${i}-n`)} value={m.name} onChange={(e) => setM({ name: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Date" htmlFor={id(`m-${i}-d`)} required>
                      <Input id={id(`m-${i}-d`)} type="date" value={m.date} onChange={(e) => setM({ date: e.target.value })} className="bg-surface" />
                    </Field>
                    {inBrief.length > 0 && (
                      <div className="space-y-1.5 sm:col-span-2" role="group" aria-label="Regions for this moment">
                        <p className="text-[13px] font-medium text-ink">Regions <span className="font-normal text-ink-secondary">(none means all)</span></p>
                        <div className="flex flex-wrap gap-1.5">
                          {inBrief.map((code) => (
                            <ToggleChip key={code} pressed={m.region_codes.includes(code)} onClick={() => setM({ region_codes: m.region_codes.includes(code) ? m.region_codes.filter((c) => c !== code) : [...m.region_codes, code] })}>
                              {nameOf(code)}
                            </ToggleChip>
                          ))}
                        </div>
                      </div>
                    )}
                    {dates.sources.some((s) => !blank(s.title)) && (
                      <div className="space-y-1.5 sm:col-span-2" role="group" aria-label="Sources for this moment">
                        <p className="text-[13px] font-medium text-ink">Sources</p>
                        <div className="flex flex-wrap gap-1.5">
                          {dates.sources.filter((s) => !blank(s.title)).map((s) => {
                            const sid = s.id || slugify(s.title);
                            return (
                              <ToggleChip key={sid} pressed={m.source_ids.includes(sid)} onClick={() => setM({ source_ids: m.source_ids.includes(sid) ? m.source_ids.filter((x) => x !== sid) : [...m.source_ids, sid] })}>
                                {s.publisher || s.title}
                              </ToggleChip>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    <Field label="Note" htmlFor={id(`m-${i}-note`)} className="sm:col-span-2">
                      <Input id={id(`m-${i}-note`)} value={m.note ?? ""} onChange={(e) => setM({ note: e.target.value })} className="bg-surface" />
                    </Field>
                  </div>
                )}
              />
            </div>
          </>
        )}
      </Group>

      <Group legend="Success metric" hint="How the campaign will be judged. Targets are planning inputs, not predictions.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Primary metric" htmlFor={id("sm-name")} required hint="For example cost per order.">
            <Input id={id("sm-name")} value={metric ? metric.primary.id.replace(/[_-]/g, " ") : ""} onChange={(e) => set({ success_metric: { secondary: [], note: null, ...metric, primary: { definition: "", target: null, ...metric?.primary, id: e.target.value } } })} className="bg-surface" />
          </Field>
          <Field label="Target" htmlFor={id("sm-target")}>
            <Input id={id("sm-target")} value={metric?.primary.target ?? ""} onChange={(e) => set({ success_metric: { secondary: [], note: null, ...metric, primary: { id: "", definition: "", ...metric?.primary, target: e.target.value } } })} className="bg-surface" />
          </Field>
          <Field label="Definition" htmlFor={id("sm-def")} className="sm:col-span-2">
            <Textarea id={id("sm-def")} rows={2} value={metric?.primary.definition ?? ""} onChange={(e) => set({ success_metric: { secondary: [], note: null, ...metric, primary: { id: "", target: null, ...metric?.primary, definition: e.target.value } } })} className="bg-surface" />
          </Field>
        </div>
        {metric && (
          <>
            <div className="space-y-2">
              <p className="text-[13px] font-medium text-ink">Secondary metrics</p>
              <Repeater
                items={metric.secondary}
                onChange={(secondary) => set({ success_metric: { ...metric, secondary } })}
                make={() => ({ id: "", definition: "", target: null as string | null })}
                addLabel="Add a secondary metric"
                noun="secondary metric"
                max={6}
                render={(m, setM, i) => (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Metric" htmlFor={id(`sec-${i}-n`)} required>
                      <Input id={id(`sec-${i}-n`)} value={m.id.replace(/[_-]/g, " ")} onChange={(e) => setM({ id: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Target" htmlFor={id(`sec-${i}-t`)}>
                      <Input id={id(`sec-${i}-t`)} value={m.target ?? ""} onChange={(e) => setM({ target: e.target.value })} className="bg-surface" />
                    </Field>
                    <Field label="Definition" htmlFor={id(`sec-${i}-d`)} className="sm:col-span-2">
                      <Input id={id(`sec-${i}-d`)} value={m.definition} onChange={(e) => setM({ definition: e.target.value })} className="bg-surface" />
                    </Field>
                  </div>
                )}
              />
            </div>
            <Field label="Note" htmlFor={id("sm-note")}>
              <Input id={id("sm-note")} value={metric.note ?? ""} onChange={(e) => set({ success_metric: { ...metric, note: e.target.value } })} className="bg-surface" />
            </Field>
          </>
        )}
      </Group>

      <Group legend="Call to action">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="In English" htmlFor={id("cta-en")}>
            <Input id={id("cta-en")} value={cta?.text_en ?? ""} onChange={(e) => set({ cta: { festival_hook: null, original: null, ...cta, text_en: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Festival hook" htmlFor={id("cta-hook")} hint="How the delivery promise ties to each region's festival day.">
            <Input id={id("cta-hook")} value={cta?.festival_hook ?? ""} onChange={(e) => set({ cta: { text_en: null, original: null, ...cta, festival_hook: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Original line" htmlFor={id("cta-orig")} hint="In the original's own language.">
            <Input id={id("cta-orig")} lang={cta?.original ? draft.languages[cta.original.region_code]?.[0] : undefined} value={cta?.original?.text ?? ""} onChange={(e) => set({ cta: { text_en: null, festival_hook: null, ...cta, original: { region_code: draft.regions.origin ?? inBrief[0] ?? "", translation_en: null, ...cta?.original, text: e.target.value } } })} className="bg-surface" />
          </Field>
          <Field label="English translation of the original line" htmlFor={id("cta-trans")}>
            <Input id={id("cta-trans")} value={cta?.original?.translation_en ?? ""} onChange={(e) => cta?.original && set({ cta: { ...cta, original: { ...cta.original, translation_en: e.target.value } } })} disabled={!cta?.original} className="bg-surface" />
          </Field>
        </div>
      </Group>

      <Group legend="Constraints" hint="One per line. Rules every version must keep.">
        <Lines id={id("constraints")} value={draft.constraints} onChange={(constraints) => set({ constraints })} rows={4} />
      </Group>

      <ServerProblems errors={errors} />
      {save.error && Object.keys(errors).length === 0 && <ErrorState error={save.error} />}
      {stale && <p className="text-[13px] text-ink-secondary">Someone saved a newer version. Cancel to reload the current brief, then apply this change again.</p>}

      <div className="space-y-3 rounded-card border border-border bg-surface p-4 sm:p-5">
        <Field label="What changed" htmlFor={id("note")} hint="Shown beside this version in the history.">
          <Input id={id("note")} value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} className="bg-surface" />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : brief.saved ? `Save as version ${brief.version + 1}` : "Save version 1"}
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>
            Cancel
          </Button>
          <p className="text-xs text-ink-secondary" aria-live="polite">
            An unchanged brief adds no version.
          </p>
        </div>
      </div>
    </form>
  );
}
