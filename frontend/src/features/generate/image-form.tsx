"use client";

import { Check, ImageOff } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/forms/fields";
import type { Region } from "@/features/desk/types";
import { cn } from "@/lib/utils";

import { useStartImage, type GenerateAssetRef, type GenerateCapabilities, type ImageFormat, type ImageRequest } from "./api";
import { addIdea, Group, languageFor, SCRIPT_NAMES, StartRow, TargetFields } from "./form-parts";
import { AssetImage } from "./images";
import { Chip, FormatGlyph, INPUT, Notice, Swatch, TEXTAREA } from "./parts";

export type ReferenceOption = { id: string; label: string; source: string; kit?: boolean; asset: Pick<GenerateAssetRef, "asset_id" | "url"> };

/** Setup for a key visual or social post: where, what format, the idea, an optional headline and reference, then run. */
export function ImageForm({
  campaignId,
  caps,
  regions,
  startRegion,
  references,
  reference,
  onReference,
  working,
  onStarted,
}: {
  campaignId: string;
  caps: GenerateCapabilities;
  regions: Region[];
  startRegion: string;
  references: ReferenceOption[];
  reference: string | null;
  onReference: (id: string | null) => void;
  working: boolean;
  onStarted: (runId: string) => void;
}) {
  const info = caps.generators.find((g) => g.kind === "image");
  const brand = caps.brand;
  const [region, setRegion] = useState(startRegion);
  const [language, setLanguage] = useState(() => languageFor(regions.find((r) => r.code === startRegion), caps.languages));
  const [format, setFormat] = useState<ImageFormat>("4:5");
  const [purpose, setPurpose] = useState<ImageRequest["purpose"]>("key_visual");
  const [idea, setIdea] = useState("");
  const [headline, setHeadline] = useState("");
  const [logo, setLogo] = useState(true);
  const [product, setProduct] = useState(true);
  const [colours, setColours] = useState(true);
  const [notes, setNotes] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const start = useStartImage(campaignId);
  const script = caps.languages.find((l) => l.code === language)?.script ?? "Latn";

  const chips = [...caps.idea_chips, ...(brand.product_name ? [`${brand.product_name} as the hero`] : []), ...brand.festival_hooks.slice(0, 2).map((f) => `${f} mood`)];
  const blocked = idea.trim() ? null : "Describe the scene to continue.";
  // The real product is placed in code, so the Brand Kit pack is never also shown to the model (it would draw a second one).
  const packAsReference = product && brand.products.length > 0 && Boolean(references.find((r) => r.id === reference)?.kit);

  function submit() {
    if (start.isPending || working) return; // a double click or a held Enter never sends a second paid call
    start.mutate(
      {
        region_code: region,
        language,
        format,
        purpose,
        idea: idea.trim(),
        headline: headline.trim() || null,
        include_logo: logo && brand.logos.length > 0,
        include_product: product && brand.products.length > 0,
        reference_asset_id: packAsReference ? null : reference,
        use_brand_colours: colours,
        use_region_claims: notes,
        confirm_cost: caps.mode === "live" && confirmed,
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
      aria-label="Generate an image"
    >
      <TargetFields
        regions={regions}
        region={region}
        language={language}
        languages={caps.languages}
        onRegion={(code) => {
          setRegion(code);
          setLanguage(languageFor(regions.find((r) => r.code === code), caps.languages, language));
        }}
        onLanguage={setLanguage}
      />

      <Group legend="Format">
        <div className="flex flex-wrap gap-2">
          {caps.formats.map((f) => (
            <Chip key={f.id} pressed={format === f.id} onClick={() => setFormat(f.id)} title={`${f.width} x ${f.height} px`}>
              <FormatGlyph width={f.width} height={f.height} />
              {f.id} <span className="text-ink-secondary">{f.label}</span>
            </Chip>
          ))}
        </div>
      </Group>

      <Group legend="What is it for">
        <div className="inline-flex rounded-lg border border-border bg-surface p-0.5" role="group" aria-label="Purpose">
          {caps.purposes.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={purpose === p}
              onClick={() => setPurpose(p)}
              className={cn(
                "h-8 rounded-md px-3.5 text-[13.5px] font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/30 max-sm:h-10",
                purpose === p ? "bg-surface-raised text-ink shadow-card" : "text-ink-secondary hover:text-ink",
              )}
            >
              {p === "key_visual" ? "Key visual" : "Social post"}
            </button>
          ))}
        </div>
      </Group>

      <Field label="The idea" htmlFor="gen-idea" required hint="Your words go to the image model as yours. The brief and Brand Kit below are added as direction.">
        <textarea id="gen-idea" className={TEXTAREA} rows={3} maxLength={400} value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="A brass lamp glowing beside a tin of sweets, evening light" />
      </Field>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Prompt ideas">
        {chips.map((chip) => (
          <Chip key={chip} onClick={() => setIdea((text) => addIdea(text, chip))}>
            {chip}
          </Chip>
        ))}
      </div>

      <Field
        label="Headline"
        htmlFor="gen-headline"
        hint={`Drawn in code in ${SCRIPT_NAMES[script] ?? script} with the same renderer as Remake. The image model never draws lettering.`}
      >
        <input
          id="gen-headline"
          lang={language}
          maxLength={120}
          value={headline}
          onChange={(e) => setHeadline(e.target.value)}
          className={INPUT}
        />
      </Field>

      <Group legend="From your brief and Brand Kit">
        <div className="space-y-2.5 rounded-xl bg-surface-muted/70 p-3 shadow-well">
          {brand.logos.length > 0 && (
            <label className="flex items-center gap-2.5 text-[13.5px] text-ink-body">
              <input type="checkbox" className="size-4 accent-primary" checked={logo} onChange={(e) => setLogo(e.target.checked)} />
              Logo, placed top left in code
              <span className="flex gap-1.5">
                {brand.logos.slice(0, 2).map((l) => l.url && l.asset_id && <AssetImage key={l.id} asset={{ asset_id: l.asset_id, url: l.url }} alt={l.label} className="h-6 w-auto rounded-sm bg-spine/80 p-0.5" />)}
              </span>
            </label>
          )}
          {brand.products.length > 0 && (
            <label className="flex items-center gap-2.5 text-[13.5px] text-ink-body">
              <input type="checkbox" className="size-4 accent-primary" checked={product} onChange={(e) => setProduct(e.target.checked)} />
              Product image, placed bottom right in code
              {brand.products[0].url && brand.products[0].asset_id && <AssetImage asset={{ asset_id: brand.products[0].asset_id, url: brand.products[0].url }} alt={brand.products[0].label} className="h-6 w-auto rounded-sm" />}
            </label>
          )}
          {brand.colours.length > 0 && (
            <label className="flex flex-wrap items-center gap-2.5 text-[13.5px] text-ink-body">
              <input type="checkbox" className="size-4 accent-primary" checked={colours} onChange={(e) => setColours(e.target.checked)} />
              Brand colours as direction
              <span className="flex gap-1.5">{brand.colours.map((c) => <Swatch key={c.id} hex={c.hex} name={c.name} />)}</span>
            </label>
          )}
          <label className="flex items-center gap-2.5 text-[13.5px] text-ink-body">
            <input type="checkbox" className="size-4 accent-primary" checked={notes} onChange={(e) => setNotes(e.target.checked)} />
            A few sourced regional notes from Market Lens
          </label>
          {brand.tone.length > 0 && <p className="type-meta">Tone: {brand.tone.join(", ")}</p>}
        </div>
      </Group>

      <Group legend="Reference image" hint="Optional. The model sees it for look and styling only; the real product image is placed afterwards.">
        <ul className="flex gap-2 overflow-x-auto pb-2" aria-label="Reference images">
          <li className="shrink-0">
            <button
              type="button"
              aria-pressed={reference === null}
              onClick={() => onReference(null)}
              className={cn(
                "grid size-16 place-items-center rounded-lg border text-ink-secondary outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                reference === null ? "border-primary bg-pop-soft shadow-clay-pressed" : "border-border-strong/45 bg-surface-raised shadow-card hover:bg-surface-muted",
              )}
            >
              <ImageOff aria-hidden className="size-5" />
              <span className="sr-only">No reference image</span>
            </button>
          </li>
          {references.map((r) => (
            <li key={r.id} className="shrink-0">
              <button
                type="button"
                aria-pressed={reference === r.id}
                onClick={() => onReference(reference === r.id ? null : r.id)}
                title={`${r.label} · ${r.source}`}
                className={cn(
                  "relative block size-16 overflow-hidden rounded-lg border outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                  reference === r.id ? "border-primary shadow-clay-pressed" : "border-border-strong/45 shadow-card hover:border-border-strong",
                )}
              >
                <AssetImage asset={r.asset} alt={r.label} fit="cover" />
                {reference === r.id && (
                  <span className="absolute right-0.5 bottom-0.5 grid size-5 place-items-center rounded-full bg-primary text-primary-foreground">
                    <Check aria-hidden className="size-3" />
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
        {packAsReference && (
          <Notice tone="info">
            The Brand Kit product image is placed in code, so it is not sent to the model as a reference; the model would draw a second pack. Turn off
            &ldquo;Product image, placed bottom right&rdquo; to use it as a reference instead.
          </Notice>
        )}
      </Group>

      {start.isError && <p role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-[13.5px] text-ink">{start.error.message}</p>}
      <StartRow
        caps={caps}
        estimate={info?.estimated_cost_usd}
        what="one image call"
        label="Generate image"
        confirmed={confirmed}
        onConfirm={setConfirmed}
        working={working || start.isPending}
        blocked={blocked}
        pending={start.isPending}
      />
    </form>
  );
}
