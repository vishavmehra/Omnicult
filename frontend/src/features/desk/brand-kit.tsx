"use client";

import { BookA, CircleAlert, CircleCheck, ImageOff, Lock, PencilLine, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Swatch, TiltCard } from "@/components/creative";
import { Tag } from "@/components/evidence/badges";
import { workspaceHref } from "@/components/shell/workspaces";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { AssetImage } from "@/features/arena/asset-image";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useBrandKit } from "./api";
import { LockupCard, TypeSpecimen } from "./desk-visuals";
import { KitEditor } from "./kit-editor";
import { languageName, type BrandKit, type KitContrast } from "./types";

const Muted = ({ children }: { children: ReactNode }) => <span className="text-ink-muted">{children}</span>;

function Terms({ terms, empty }: { terms: string[]; empty: string }) {
  if (!terms.length) return <Muted>{empty}</Muted>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {terms.map((t) => (
        <li key={t} className="rounded-stamp border border-border-strong/45 bg-surface-raised px-1.5 py-0.5 text-[12.5px] text-ink">
          {t}
        </li>
      ))}
    </ul>
  );
}

function Bullets({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-[13px] text-ink-muted">{empty}</p>;
  return (
    <ul className="space-y-1 text-[13.5px] text-ink-body">
      {items.map((t) => (
        <li key={t} className="flex gap-2">
          <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-muted" />
          {t}
        </li>
      ))}
    </ul>
  );
}

function Block({ id, title, meta, children }: { id: string; title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-2.5">
      <SectionTitle id={id} meta={meta}>
        {title}
      </SectionTitle>
      {children}
    </section>
  );
}

const GRADE = {
  AAA: { Icon: CircleCheck, className: "text-success", note: "Passes AAA for any text" },
  AA: { Icon: CircleCheck, className: "text-success", note: "Passes AA for any text" },
  "AA large": { Icon: TriangleAlert, className: "text-warning", note: "Large text only (3:1)" },
  fail: { Icon: CircleAlert, className: "text-danger", note: "Fails: not for text" },
} as const;

/** One contrast pair from the API, set as a live specimen: the text colour on its background, then the ratio and grade. */
function ContrastCard({ c, names, sample, dim }: { c: KitContrast; names: Map<string, string>; sample: string; dim: boolean }) {
  const g = GRADE[c.grade];
  return (
    <li className={cn("lift overflow-hidden rounded-xl border border-border/70 bg-surface shadow-clay transition-opacity duration-200", dim && "opacity-40")}>
      <div className="flex h-24 flex-col justify-center gap-1.5 px-4" style={{ backgroundColor: c.background_hex, color: c.text_hex }}>
        <span aria-hidden className="text-[30px] leading-none font-semibold">
          Aa
        </span>
        <span className="truncate text-[13px]">{sample}</span>
      </div>
      <div className="space-y-1 px-3.5 py-2.5">
        <p className="text-[13px] text-ink-body">
          {names.get(c.text) ?? c.text} on {names.get(c.background) ?? c.background}
        </p>
        <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
          <span className="type-ledger font-semibold text-ink tabular-nums">{c.ratio.toFixed(2)}:1</span>
          <span className={cn("inline-flex items-center gap-1", g.className)}>
            <g.Icon aria-hidden className="size-4" />
            <span className="text-ink-body">
              <span className="font-medium">{c.grade}</span>. {g.note}
            </span>
          </span>
        </p>
        {c.note && <p className="text-[12px] text-ink-muted">{c.note}</p>}
      </div>
    </li>
  );
}

/** Where an image file stands: shown when uploaded, named and labelled when it is only a reference to a source file. */
function KitImage({ assetId, path, alt, className }: { assetId: string | null; path: string | null; alt: string; className?: string }) {
  if (assetId) return <AssetImage assetId={assetId} alt={alt} className={cn("bg-[repeating-conic-gradient(var(--color-surface-muted)_0%_25%,var(--color-surface)_0%_50%)] bg-[length:16px_16px] object-contain", className)} />;
  return (
    <div role="img" aria-label={`${alt} (file not uploaded)`} className={cn("flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border-strong/50 bg-surface-muted/60 p-2 text-center", className)}>
      <ImageOff aria-hidden className="size-5 text-ink-muted" />
      <span className="text-[11.5px] text-ink-muted">Not uploaded</span>
      {path && <span className="font-mono text-[10.5px] break-all text-ink-muted">{path}</span>}
    </div>
  );
}

/** The Brand Kit, read: identity, logo, colours with calculated contrast, fonts by script, tone, never-change zones, terms. */
export function BrandKitView({ kit, campaignId }: { kit: BrandKit; campaignId: string }) {
  const d = kit.design;
  // Hovering a colour lights the contrast pairs it belongs to.
  const [lit, setLit] = useState<string | null>(null);
  const colourName = new Map(d.colours.map((c) => [c.id, c.name]));
  const fixture = kit.provenance.source === "demo_fixture";
  const empty = !kit.saved;
  const protectedRule = new Map(d.protected_term_rules.map((r) => [r.term, r.rule]));

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="type-title text-[28px] text-ink">{kit.name}</h3>
          {kit.saved ? (
            <span className="type-meta" title={kit.updated_at ?? undefined}>
              Brand Kit revision {kit.revision} · saved {formatRelative(kit.updated_at)}
            </span>
          ) : (
            <span className="type-meta">No design saved yet</span>
          )}
        </div>
        {d.category && <p className="text-[13.5px] text-ink-secondary">{d.category}</p>}
        {kit.description && <p className="max-w-[68ch] text-[14.5px] text-ink-body">{kit.description}</p>}
        {d.name_meaning && <p className="max-w-[68ch] text-[13px] text-ink-secondary">{d.name_meaning}</p>}
        {(fixture || d.fictional) && <p className="text-[11.5px] text-ink-muted">Source: demonstration fixture{d.fictional ? ", fictional brand" : ""}</p>}
      </header>

      {empty && (
        <EmptyState
          title="The Brand Kit has no design yet"
          description="Add the logo lockups, colours, fonts for each script, tone of voice and the elements that must never change. Studio, Audience Lab and Risk Check read the brand record below in the meantime."
          needs={[
            { label: "Logo lockups", met: false },
            { label: "Colours", met: false },
            { label: "Fonts for each script", met: false },
            { label: "Never-change zones", met: false },
          ]}
        />
      )}

      {d.tagline && (
        <Block id="k-tagline" title="Tagline">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span lang={d.tagline.language ?? undefined} className="type-title text-[22px] text-ink">
              {d.tagline.text}
            </span>
            {d.tagline.locked && (
              <Tag className="border-border bg-surface-muted text-ink">
                <Lock aria-hidden />
                Locked
              </Tag>
            )}
            {!d.tagline.translate && <Tag className="border-border bg-surface-muted text-ink">Never translated</Tag>}
          </p>
          {d.tagline.note && <p className="text-[13px] text-ink-secondary">{d.tagline.note}</p>}
        </Block>
      )}

      {d.logo.lockups.length > 0 && (
        <Block id="k-logo" title="Logo" meta={`${d.logo.lockups.length} lockups · preview each on the brand colours`}>
          {d.logo.description && <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">{d.logo.description}</p>}
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {d.logo.lockups.map((l) => (
              <LockupCard key={l.id} lockup={l} kitName={kit.name} colours={d.colours} />
            ))}
          </ul>
          {(d.logo.clear_space || Object.keys(d.logo.min_width_px).length > 0) && (
            <p className="type-ledger text-[12.5px] text-ink-secondary">
              {d.logo.clear_space && <>Clear space: {d.logo.clear_space} </>}
              {Object.keys(d.logo.min_width_px).length > 0 && <>Minimum width: {Object.entries(d.logo.min_width_px).map(([k, n]) => `${k} ${n} px`).join(", ")}.</>}
            </p>
          )}
          {d.logo.rules.length > 0 && <Bullets items={d.logo.rules} empty="" />}
        </Block>
      )}

      {d.colours.length > 0 && (
        <Block id="k-colours" title="Colours" meta="Click a colour to copy its hex · contrast is calculated from the hex values (WCAG 2.x)">
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {d.colours.map((c) => (
              <li
                key={c.id}
                onPointerEnter={() => setLit(c.id)}
                onPointerLeave={() => setLit(null)}
                onFocus={() => setLit(c.id)}
                onBlur={() => setLit(null)}
              >
                <Swatch hex={c.hex} name={c.name} role={c.role} className="h-full" />
              </li>
            ))}
          </ul>
          {kit.contrast.length > 0 && (
            <ul aria-label="Colour contrast" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {kit.contrast.map((c) => (
                <ContrastCard key={`${c.text}-${c.background}`} c={c} names={colourName} sample={d.tagline?.text ?? kit.name} dim={lit !== null && lit !== c.text && lit !== c.background} />
              ))}
            </ul>
          )}
        </Block>
      )}

      {d.fonts.length > 0 && (
        <Block id="k-fonts" title="Fonts by script" meta="Change the weight and size to test each face">
          <ul className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {d.fonts.map((f) => (
              <TypeSpecimen key={f.family} font={f} sample={d.tagline?.language === "en" ? d.tagline.text : null} />
            ))}
          </ul>
          {d.typography_rules.length > 0 && <Bullets items={d.typography_rules} empty="" />}
        </Block>
      )}

      <Block id="k-tone" title="Tone of voice">
        {d.tone_of_voice.summary ? <p className="max-w-[68ch] text-[14.5px] text-ink-body">{d.tone_of_voice.summary}</p> : kit.communication_style ? <p className="max-w-[68ch] text-[14.5px] text-ink-body">{kit.communication_style}</p> : <Muted>No tone summary yet.</Muted>}
        <Terms terms={d.tone_of_voice.traits.length ? d.tone_of_voice.traits : kit.voice} empty="No voice traits yet" />
        {(d.tone_of_voice.do.length > 0 || d.tone_of_voice.dont.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <p className="type-meta inline-flex items-center gap-1.5 text-success">
                <CircleCheck aria-hidden className="size-3.5" />
                Do
              </p>
              <Bullets items={d.tone_of_voice.do} empty="Nothing listed." />
            </div>
            <div className="space-y-1.5">
              <p className="type-meta inline-flex items-center gap-1.5 text-danger">
                <CircleAlert aria-hidden className="size-3.5" />
                Do not
              </p>
              <Bullets items={d.tone_of_voice.dont} empty="Nothing listed." />
            </div>
          </div>
        )}
      </Block>

      {d.never_change.length > 0 && (
        <Block id="k-never" title="Never change" meta="Lock these on every version in Creative Studio">
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {d.never_change.map((n) => (
              <li key={n.id} className="space-y-1 px-4 py-3">
                <p className="flex items-center gap-2 text-[13.5px] font-medium text-ink">
                  <Lock aria-hidden className="size-3.5 text-ink-muted" />
                  {n.id.replace(/[_-]/g, " ")}
                </p>
                <p className="text-[13.5px] text-ink-body">{n.description}</p>
                {n.text && <p className="text-[13px] text-ink-secondary">“{n.text}”</p>}
                {Object.entries(n.regions).map(([name, box]) => (
                  <p key={name} className="type-ledger text-[12px] text-ink-muted">
                    {name.replace(/_/g, " ")}: x {box[0]}, y {box[1]}, width {box[2]}, height {box[3]} (share of the image){n.bbox_note ? `. ${n.bbox_note}` : ""}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Block id="k-terms" title="Terms" meta="From the brand record">
        <dl className="ledger-rules rounded-card border border-border bg-surface">
          <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger inline-flex items-center gap-1 text-[12.5px] text-ink-muted">
              <Lock aria-hidden className="size-3" />
              Protected
            </dt>
            <dd className="space-y-1.5">
              <Terms terms={kit.protected_terms} empty="None protected" />
              {kit.protected_terms.some((t) => protectedRule.get(t)) && (
                <ul className="space-y-0.5 text-[12.5px] text-ink-secondary">
                  {kit.protected_terms.map((t) => protectedRule.get(t) && <li key={t}><span className="font-medium text-ink-body">{t}:</span> {protectedRule.get(t)}</li>)}
                </ul>
              )}
            </dd>
          </div>
          <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">Preferred</dt>
            <dd><Terms terms={kit.preferred_terms} empty="None listed" /></dd>
          </div>
          <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">Prohibited</dt>
            <dd><Terms terms={kit.prohibited_terms} empty="None listed" /></dd>
          </div>
        </dl>
        <p className="text-[12.5px] text-ink-muted">
          Term lists are edited on the brand record.{" "}
          <Link href={`/projects/${kit.project_id}/brand?campaign=${campaignId}`} className="font-medium text-rose hover:underline">
            Edit the brand record
          </Link>
        </p>
      </Block>

      {(d.claims_policy.allowed.length > 0 || d.claims_policy.forbidden.length > 0) && (
        <Block id="k-claims" title="Claims policy">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <p className="type-meta">Allowed</p>
              <Bullets items={d.claims_policy.allowed} empty="Nothing listed." />
            </div>
            <div className="space-y-1.5">
              <p className="type-meta">Forbidden</p>
              <Bullets items={d.claims_policy.forbidden} empty="Nothing listed." />
            </div>
          </div>
        </Block>
      )}

      {d.product_images.length > 0 && (
        <Block id="k-images" title="Product images">
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {d.product_images.map((p) => (
              <TiltCard as="li" key={p.id} max={4} className="bento space-y-2 p-3">
                <KitImage assetId={p.asset_id} path={p.source_path} alt={p.description ?? `${kit.name} product image ${p.id}`} className="h-44 w-full" />
                <p className="text-[13.5px] font-medium text-ink capitalize">{p.id.replace(/[_-]/g, " ")}</p>
                {p.description && <p className="text-[12.5px] text-ink-secondary">{p.description}</p>}
                {p.provenance && <p className="text-[11.5px] text-ink-muted">{p.provenance}</p>}
              </TiltCard>
            ))}
          </ul>
        </Block>
      )}

      <Block id="k-glossary" title="Brand Glossary" meta="Lives in Creative Studio">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-border bg-surface px-4 py-3">
          <BookA aria-hidden className="size-5 text-ink-muted" />
          <p className="type-ledger text-[13.5px] tabular-nums text-ink-body">
            {kit.glossary.term_count} {kit.glossary.term_count === 1 ? "term" : "terms"}
            <span className="text-ink-muted"> · </span>
            {kit.glossary.protected_count} protected
            <span className="text-ink-muted"> · </span>
            {kit.glossary.never_translate_count} never translated
            {kit.glossary.languages.length > 0 && (
              <>
                <span className="text-ink-muted"> · </span>
                {kit.glossary.languages.map(languageName).join(", ")}
              </>
            )}
          </p>
          <Link href={`${workspaceHref(campaignId, "studio")}?tab=glossary`} className="ml-auto text-[13.5px] font-medium text-rose hover:underline">
            Open the Brand Glossary
          </Link>
        </div>
        {kit.glossary.term_count === 0 && <p className="text-[12.5px] text-ink-muted">No glossary terms yet. Spellings by script, pronunciation and do-not-translate terms are added in Creative Studio.</p>}
      </Block>
    </div>
  );
}

/** The Brand Kit tab: loads the kit, offers edit mode, and says why editing is unavailable when it is. */
export function BrandKitTab({ projectId, campaignId }: { projectId: string; campaignId: string }) {
  const q = useBrandKit(projectId);
  const [editing, setEditing] = useState(false);
  if (q.isPending) return <LoadingState label="Loading the Brand Kit…" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const kit = q.data;
  if (editing && kit.editable) return <KitEditor kit={kit} projectId={projectId} onCancel={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[60ch] text-[13px] text-ink-secondary">
          {kit.editable
            ? "Voice and the term lists come from the brand record that Creative Studio, Audience Lab and Risk Check read. Logo, colours, fonts and the never-change zones are stored in the Brand Kit."
            : (kit.locked_reason ?? "This Brand Kit is read-only.")}
        </p>
        {kit.editable && (
          <Button variant="outline" onClick={() => setEditing(true)}>
            <PencilLine aria-hidden />
            {kit.saved ? "Edit the Brand Kit" : "Set up the Brand Kit"}
          </Button>
        )}
      </div>
      <BrandKitView kit={kit} campaignId={campaignId} />
    </div>
  );
}
