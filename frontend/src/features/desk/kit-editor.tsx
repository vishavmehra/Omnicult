"use client";

import { useId, useState, type FormEvent } from "react";

import { Field, TermListInput } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { AssetImage } from "@/features/arena/asset-image";
import { AssetUploader } from "@/features/assets/asset-uploader";
import { serverFieldErrors } from "@/features/atlas/form-errors";

import { useSaveBrandKit } from "./api";
import { Group, Lines, Repeater, Select, ServerProblems, ToggleChip } from "./form-parts";
import { SCRIPTS, scriptName, uniqueSlug, type BrandKit, type KitDesign } from "./types";

type Lockup = KitDesign["logo"]["lockups"][number];
type Colour = KitDesign["colours"][number];
type Pair = KitDesign["contrast_pairs"][number];
type Font = KitDesign["fonts"][number];
type Rule = KitDesign["protected_term_rules"][number];
type Never = KitDesign["never_change"][number];
type Image = KitDesign["product_images"][number];

const SLUG = /^[a-z0-9][a-z0-9_.-]{0,63}$/;
const blank = (s: string | null | undefined) => !s || !s.trim();
const text = (s: string | null | undefined) => (blank(s) ? null : s!.trim());
const toId = (raw: string, taken: string[], fallback: string) => (SLUG.test(raw) && !taken.includes(raw) ? raw : uniqueSlug(raw, taken, fallback));
const AUTO_COLOUR_ID = /^colour(-\d+)?$/;

/** "400, 600" while typing; the list is reported only from numbers that parse. */
function WeightsInput({ id, value, onChange }: { id: string; value: number[]; onChange(next: number[]): void }) {
  const [raw, setRaw] = useState(value.join(", "));
  return (
    <Input
      id={id}
      value={raw}
      inputMode="numeric"
      placeholder="400, 600"
      className="bg-surface tabular-nums"
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(e.target.value.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n >= 100 && n <= 900));
      }}
    />
  );
}

/** Empty text becomes null, unnamed rows disappear, ids are made from names and kept unique. */
function cleanDesign(d: KitDesign): KitDesign {
  const lockupIds: string[] = [];
  const lockups = d.logo.lockups
    .filter((l) => !blank(l.id) || !blank(l.use) || l.asset_id)
    .map((l) => {
      const id = toId(l.id, lockupIds, "lockup");
      lockupIds.push(id);
      return { ...l, id, use: l.use.trim() || id };
    });
  const colourIds = d.colours.map((c) => c.id);
  const neverIds: string[] = [];
  const imageIds: string[] = [];
  return {
    ...d,
    category: text(d.category),
    tagline: d.tagline && !blank(d.tagline.text) ? { ...d.tagline, text: d.tagline.text.trim(), language: text(d.tagline.language), note: text(d.tagline.note) } : null,
    logo: { ...d.logo, description: text(d.logo.description), clear_space: text(d.logo.clear_space), lockups },
    colours: d.colours.filter((c) => !blank(c.name)).map((c) => ({ ...c, name: c.name.trim(), hex: c.hex.trim(), role: text(c.role) })),
    contrast_pairs: d.contrast_pairs.filter((p) => colourIds.includes(p.text) && colourIds.includes(p.background)).map((p) => ({ ...p, note: text(p.note) })),
    fonts: d.fonts.filter((f) => !blank(f.family) && f.scripts.length).map((f) => ({ ...f, family: f.family.trim(), role: text(f.role), license: text(f.license), source: text(f.source) })),
    tone_of_voice: { ...d.tone_of_voice, summary: text(d.tone_of_voice.summary) },
    protected_term_rules: d.protected_term_rules.filter((r) => !blank(r.term)).map((r) => ({ term: r.term.trim(), rule: text(r.rule) })),
    never_change: d.never_change
      .filter((n) => !blank(n.description))
      .map((n) => {
        const id = toId(blank(n.id) ? n.description.split(/\s+/).slice(0, 3).join(" ") : n.id, neverIds, "zone");
        neverIds.push(id);
        return { ...n, id, description: n.description.trim(), text: text(n.text), bbox_note: text(n.bbox_note) };
      }),
    product_images: d.product_images
      .filter((p) => !blank(p.id) || !blank(p.description) || p.asset_id)
      .map((p) => {
        const id = toId(blank(p.id) ? (p.description ?? "image") : p.id, imageIds, "image");
        imageIds.push(id);
        return { ...p, id, description: text(p.description), provenance: text(p.provenance), background: text(p.background) };
      }),
  };
}

/** Edit the design half of the Brand Kit. The whole design is replaced; images are uploaded through the existing asset upload. */
export function KitEditor({ kit, projectId, onCancel, onSaved }: { kit: BrandKit; projectId: string; onCancel(): void; onSaved(): void }) {
  const uid = useId();
  const id = (name: string) => `${uid}-${name}`;
  const [draft, setDraft] = useState<KitDesign>(() => structuredClone(kit.design));
  const save = useSaveBrandKit(projectId);
  const errors = serverFieldErrors(save.error);
  const set = (patch: Partial<KitDesign>) => setDraft((d) => ({ ...d, ...patch }));
  const setLogo = (patch: Partial<KitDesign["logo"]>) => setDraft((d) => ({ ...d, logo: { ...d.logo, ...patch } }));
  const setTone = (patch: Partial<KitDesign["tone_of_voice"]>) => setDraft((d) => ({ ...d, tone_of_voice: { ...d.tone_of_voice, ...patch } }));
  const setClaims = (patch: Partial<KitDesign["claims_policy"]>) => setDraft((d) => ({ ...d, claims_policy: { ...d.claims_policy, ...patch } }));

  function setColours(next: Colour[], pairs: Pair[] = draft.contrast_pairs) {
    set({ colours: next, contrast_pairs: pairs });
  }

  function rename(index: number, name: string) {
    const c = draft.colours[index]!;
    let nextId = c.id;
    if (!c.id || AUTO_COLOUR_ID.test(c.id)) nextId = uniqueSlug(name, draft.colours.filter((_, i) => i !== index).map((x) => x.id), "colour");
    const pairs = draft.contrast_pairs.map((p) => ({ ...p, text: p.text === c.id ? nextId : p.text, background: p.background === c.id ? nextId : p.background }));
    setColours(draft.colours.map((x, i) => (i === index ? { ...x, name, id: nextId } : x)), pairs);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (save.isPending) return;
    save.mutate({ design: cleanDesign(draft), expectedRevision: kit.revision }, { onSuccess: onSaved });
  }

  const tone = draft.tone_of_voice;
  const colourOptions = draft.colours.filter((c) => c.id && !blank(c.name));

  return (
    <form onSubmit={submit} className="space-y-5" aria-label="Edit the Brand Kit">
      <Group legend="Identity" hint="The name, voice words and term lists belong to the brand record and are edited there.">
        <Field label="Category" htmlFor={id("category")}>
          <Input id={id("category")} value={draft.category ?? ""} onChange={(e) => set({ category: e.target.value })} className="bg-surface" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Tagline" htmlFor={id("tag")}>
            <Input id={id("tag")} value={draft.tagline?.text ?? ""} onChange={(e) => set({ tagline: { language: null, script: null, locked: false, translate: true, note: null, ...draft.tagline, text: e.target.value } })} className="bg-surface" />
          </Field>
          <Field label="Tagline language" htmlFor={id("tag-lang")} hint="ISO 639-1, for example en.">
            <Input id={id("tag-lang")} maxLength={3} value={draft.tagline?.language ?? ""} disabled={!draft.tagline} onChange={(e) => draft.tagline && set({ tagline: { ...draft.tagline, language: e.target.value.toLowerCase() } })} className="bg-surface" />
          </Field>
        </div>
        {draft.tagline && (
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13.5px] text-ink">
            <label className="flex items-center gap-2">
              <input type="checkbox" className="size-4 accent-[var(--ember)]" checked={draft.tagline.locked} onChange={(e) => set({ tagline: { ...draft.tagline!, locked: e.target.checked } })} />
              Locked: never altered
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="size-4 accent-[var(--ember)]" checked={!draft.tagline.translate} onChange={(e) => set({ tagline: { ...draft.tagline!, translate: !e.target.checked } })} />
              Never translated
            </label>
          </div>
        )}
      </Group>

      <Group legend="Logo" hint="Upload each lockup as PNG, JPEG or WebP. The vector original stays with the brand's own files.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Description" htmlFor={id("logo-desc")} className="sm:col-span-2">
            <Textarea id={id("logo-desc")} rows={2} value={draft.logo.description ?? ""} onChange={(e) => setLogo({ description: e.target.value })} className="bg-surface" />
          </Field>
          <Field label="Clear space" htmlFor={id("logo-clear")} className="sm:col-span-2">
            <Input id={id("logo-clear")} value={draft.logo.clear_space ?? ""} onChange={(e) => setLogo({ clear_space: e.target.value })} className="bg-surface" />
          </Field>
        </div>
        <Repeater<Lockup>
          items={draft.logo.lockups}
          onChange={(lockups) => setLogo({ lockups })}
          make={() => ({ id: "", use: "", source_path: null, vector_path: null, asset_id: null })}
          addLabel="Add a lockup"
          noun="lockup"
          max={12}
          empty="No lockups yet."
          render={(l, setL, i) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor={id(`lk-${i}-id`)} required hint="Lowercase letters, digits, - and _ (for example primary).">
                <Input id={id(`lk-${i}-id`)} value={l.id} onChange={(e) => setL({ id: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Use" htmlFor={id(`lk-${i}-use`)} required>
                <Input id={id(`lk-${i}-use`)} value={l.use} onChange={(e) => setL({ use: e.target.value })} className="bg-surface" />
              </Field>
              <div className="space-y-2 sm:col-span-2">
                {l.asset_id && <AssetImage assetId={l.asset_id} alt={`Uploaded ${l.id || "logo"} lockup`} className="h-20 w-40 object-contain" />}
                {!l.asset_id && l.source_path && <p className="font-mono text-[11.5px] text-ink-muted">Source file {l.source_path}, not uploaded.</p>}
                <AssetUploader projectId={projectId} kind="image" label={l.asset_id ? "Replace the image" : "Upload the image"} onUploaded={(a) => setL({ asset_id: a.id, source_path: a.filename })} />
              </div>
            </div>
          )}
        />
        <Field label="Logo rules" htmlFor={id("logo-rules")} hint="One per line.">
          <Lines id={id("logo-rules")} value={draft.logo.rules} onChange={(rules) => setLogo({ rules })} />
        </Field>
      </Group>

      <Group legend="Colours" hint="Contrast ratios are calculated from the hex values; they are never typed in.">
        <Repeater<Colour>
          items={draft.colours}
          onChange={(next) => setColours(next, draft.contrast_pairs.filter((p) => next.some((c) => c.id === p.text) && next.some((c) => c.id === p.background)))}
          make={() => ({ id: "", name: "", hex: "#808080", role: null })}
          addLabel="Add a colour"
          noun="colour"
          max={24}
          empty="No colours yet."
          render={(c, _set, i) => (
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_minmax(0,1.4fr)]">
              <Field label="Name" htmlFor={id(`co-${i}-n`)} required>
                <Input id={id(`co-${i}-n`)} value={c.name} onChange={(e) => rename(i, e.target.value)} className="bg-surface" />
              </Field>
              <Field label="Hex" htmlFor={id(`co-${i}-h`)} required>
                <span className="flex items-center gap-1.5">
                  <input type="color" aria-label={`Pick a colour for ${c.name || "colour " + (i + 1)}`} value={/^#[0-9a-f]{6}$/i.test(c.hex) ? c.hex : "#808080"} onChange={(e) => setColours(draft.colours.map((x, j) => (j === i ? { ...x, hex: e.target.value.toUpperCase() } : x)))} className="h-8 w-9 shrink-0 cursor-pointer rounded-md border border-input bg-surface p-0.5" />
                  <Input id={id(`co-${i}-h`)} value={c.hex} maxLength={7} onChange={(e) => setColours(draft.colours.map((x, j) => (j === i ? { ...x, hex: e.target.value } : x)))} className="bg-surface font-mono text-[12px] uppercase" />
                </span>
              </Field>
              <Field label="Role" htmlFor={id(`co-${i}-r`)}>
                <Input id={id(`co-${i}-r`)} value={c.role ?? ""} onChange={(e) => setColours(draft.colours.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} className="bg-surface" />
              </Field>
            </div>
          )}
        />
        <div className="space-y-2">
          <p className="text-[13px] font-medium text-ink">Colour pairs to check</p>
          <Repeater<Pair>
            items={draft.contrast_pairs}
            onChange={(contrast_pairs) => set({ contrast_pairs })}
            make={() => ({ text: colourOptions[0]?.id ?? "", background: colourOptions[1]?.id ?? colourOptions[0]?.id ?? "", note: null })}
            addLabel="Add a pair"
            noun="pair"
            max={40}
            empty={colourOptions.length < 2 ? "Add at least two colours to check a pair." : "No pairs yet."}
            render={(p, setP, i) => (
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Text" htmlFor={id(`pr-${i}-t`)} required>
                  <Select id={id(`pr-${i}-t`)} value={p.text} onChange={(v) => setP({ text: v })}>
                    {colourOptions.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="On background" htmlFor={id(`pr-${i}-b`)} required>
                  <Select id={id(`pr-${i}-b`)} value={p.background} onChange={(v) => setP({ background: v })}>
                    {colourOptions.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Note" htmlFor={id(`pr-${i}-n`)}>
                  <Input id={id(`pr-${i}-n`)} value={p.note ?? ""} onChange={(e) => setP({ note: e.target.value })} className="bg-surface" />
                </Field>
              </div>
            )}
          />
        </div>
      </Group>

      <Group legend="Fonts by script" hint="One face per role and script. Indic text is always set in type with these fonts, never drawn by an image model.">
        <Repeater<Font>
          items={draft.fonts}
          onChange={(fonts) => set({ fonts })}
          make={() => ({ family: "", weights: [], scripts: ["Latn"], role: null, license: null, source: null })}
          addLabel="Add a font"
          noun="font"
          max={24}
          empty="No fonts yet."
          render={(f, setF, i) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Family" htmlFor={id(`fo-${i}-f`)} required>
                <Input id={id(`fo-${i}-f`)} value={f.family} onChange={(e) => setF({ family: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Weights" htmlFor={id(`fo-${i}-w`)}>
                <WeightsInput id={id(`fo-${i}-w`)} value={f.weights} onChange={(weights) => setF({ weights })} />
              </Field>
              <div className="space-y-1.5 sm:col-span-2" role="group" aria-label="Scripts this font covers">
                <p className="text-[13px] font-medium text-ink">Scripts</p>
                <div className="flex flex-wrap gap-1.5">
                  {SCRIPTS.map((s) => (
                    <ToggleChip key={s} pressed={f.scripts.includes(s)} onClick={() => setF({ scripts: f.scripts.includes(s) ? f.scripts.filter((x) => x !== s) : [...f.scripts, s] })}>
                      {scriptName(s)}
                    </ToggleChip>
                  ))}
                </div>
              </div>
              <Field label="Role" htmlFor={id(`fo-${i}-r`)}>
                <Input id={id(`fo-${i}-r`)} value={f.role ?? ""} onChange={(e) => setF({ role: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Licence" htmlFor={id(`fo-${i}-l`)}>
                <Input id={id(`fo-${i}-l`)} value={f.license ?? ""} onChange={(e) => setF({ license: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Source link" htmlFor={id(`fo-${i}-s`)} className="sm:col-span-2" hint="Must start with http:// or https://">
                <Input id={id(`fo-${i}-s`)} type="url" value={f.source ?? ""} onChange={(e) => setF({ source: e.target.value })} className="bg-surface" />
              </Field>
            </div>
          )}
        />
        <Field label="Typography rules" htmlFor={id("type-rules")} hint="One per line.">
          <Lines id={id("type-rules")} value={draft.typography_rules} onChange={(typography_rules) => set({ typography_rules })} />
        </Field>
      </Group>

      <Group legend="Tone of voice">
        <Field label="Summary" htmlFor={id("tone-sum")}>
          <Textarea id={id("tone-sum")} rows={2} value={tone.summary ?? ""} onChange={(e) => setTone({ summary: e.target.value })} className="bg-surface" />
        </Field>
        <Field label="Traits" htmlFor={id("tone-traits")} hint="Up to 10 short words. Press Enter to add.">
          <TermListInput id={id("tone-traits")} value={tone.traits} onChange={(traits) => setTone({ traits })} max={10} placeholder="Add a trait" />
        </Field>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Do" htmlFor={id("tone-do")} hint="One per line.">
            <Lines id={id("tone-do")} value={tone.do} onChange={(next) => setTone({ do: next })} rows={4} />
          </Field>
          <Field label="Do not" htmlFor={id("tone-dont")} hint="One per line.">
            <Lines id={id("tone-dont")} value={tone.dont} onChange={(dont) => setTone({ dont })} rows={4} />
          </Field>
        </div>
      </Group>

      <Group legend="Never change" hint="Elements and zones that no adaptation may alter. Lock them on each version in Creative Studio.">
        <Repeater<Never>
          items={draft.never_change}
          onChange={(never_change) => set({ never_change })}
          make={() => ({ id: "", description: "", assets: [], text: null, regions: {}, bbox_note: null })}
          addLabel="Add an element"
          noun="element"
          max={20}
          empty="Nothing listed yet."
          render={(n, setN, i) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor={id(`nc-${i}-id`)} hint="For example logo or tagline.">
                <Input id={id(`nc-${i}-id`)} value={n.id} onChange={(e) => setN({ id: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Exact text" htmlFor={id(`nc-${i}-t`)} hint="When the element is a line of text.">
                <Input id={id(`nc-${i}-t`)} value={n.text ?? ""} onChange={(e) => setN({ text: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="What must not change" htmlFor={id(`nc-${i}-d`)} required className="sm:col-span-2">
                <Textarea id={id(`nc-${i}-d`)} rows={2} value={n.description} onChange={(e) => setN({ description: e.target.value })} className="bg-surface" />
              </Field>
            </div>
          )}
        />
      </Group>

      <Group legend="Terms and claims">
        <p className="text-[12.5px] text-ink-secondary">
          Protected terms ({kit.protected_terms.length ? kit.protected_terms.join(", ") : "none"}) come from the brand record. Add the rule each one follows here.
        </p>
        <Repeater<Rule>
          items={draft.protected_term_rules}
          onChange={(protected_term_rules) => set({ protected_term_rules })}
          make={() => ({ term: kit.protected_terms[0] ?? "", rule: null })}
          addLabel="Add a term rule"
          noun="term rule"
          max={30}
          empty="No term rules."
          render={(r, setR, i) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Term" htmlFor={id(`tr-${i}-t`)} required>
                <Input id={id(`tr-${i}-t`)} value={r.term} onChange={(e) => setR({ term: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Rule" htmlFor={id(`tr-${i}-r`)}>
                <Input id={id(`tr-${i}-r`)} value={r.rule ?? ""} onChange={(e) => setR({ rule: e.target.value })} className="bg-surface" />
              </Field>
            </div>
          )}
        />
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Claims allowed" htmlFor={id("claims-ok")} hint="One per line.">
            <Lines id={id("claims-ok")} value={draft.claims_policy.allowed} onChange={(allowed) => setClaims({ allowed })} rows={3} />
          </Field>
          <Field label="Claims forbidden" htmlFor={id("claims-no")} hint="One per line.">
            <Lines id={id("claims-no")} value={draft.claims_policy.forbidden} onChange={(forbidden) => setClaims({ forbidden })} rows={3} />
          </Field>
        </div>
      </Group>

      <Group legend="Product images">
        <Repeater<Image>
          items={draft.product_images}
          onChange={(product_images) => set({ product_images })}
          make={() => ({ id: "", source_path: null, asset_id: null, width: null, height: null, background: null, description: null, provenance: null })}
          addLabel="Add a product image"
          noun="product image"
          max={20}
          empty="No product images yet."
          render={(p, setP, i) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor={id(`pi-${i}-id`)} hint="For example pack.">
                <Input id={id(`pi-${i}-id`)} value={p.id} onChange={(e) => setP({ id: e.target.value })} className="bg-surface" />
              </Field>
              <Field label="Description" htmlFor={id(`pi-${i}-d`)}>
                <Input id={id(`pi-${i}-d`)} value={p.description ?? ""} onChange={(e) => setP({ description: e.target.value })} className="bg-surface" />
              </Field>
              <div className="space-y-2 sm:col-span-2">
                {p.asset_id && <AssetImage assetId={p.asset_id} alt={p.description ?? `Product image ${p.id}`} className="h-28 w-40 object-contain" />}
                <AssetUploader projectId={projectId} kind="image" label={p.asset_id ? "Replace the image" : "Upload the image"} onUploaded={(a) => setP({ asset_id: a.id, source_path: a.filename, width: a.width, height: a.height })} />
              </div>
            </div>
          )}
        />
      </Group>

      <ServerProblems errors={errors} />
      {save.error && Object.keys(errors).length === 0 && <ErrorState error={save.error} />}
      <div className="flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface p-4 sm:p-5">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : kit.saved ? `Save as revision ${kit.revision + 1}` : "Save the Brand Kit"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>
          Cancel
        </Button>
        <p className="text-xs text-ink-secondary">An unchanged kit adds no revision.</p>
      </div>
    </form>
  );
}
