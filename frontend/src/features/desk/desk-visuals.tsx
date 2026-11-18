"use client";

import { ArrowUpRight, CalendarRange, Film, ImageOff, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";

import {
  ApiImage,
  ChipToggleGroup,
  CountUp,
  EmptyIllustration,
  FilmStrip,
  INDIA_TILES,
  IndiaTileMap,
  RingGauge,
  TiltCard,
  TimelineRibbon,
  roleColor,
  type RoleKey,
  type TileDatum,
} from "@/components/creative";
import { workspaceHref } from "@/components/shell/workspaces";
import { EmptyState } from "@/components/states";
import { useCreatives, useScenes } from "@/features/xray/api";
import { clock } from "@/features/xray/parts";
import type { Campaign } from "@/lib/api/types";
import { WEIGHT_FIELDS } from "@/lib/scoring";
import { cn } from "@/lib/utils";

import { dayLabel, daysBetween, formatMoney, languageName, scriptName, type Brief, type BriefContent, type KitDesign, type Region } from "./types";

/*
 * Campaign Desk, visual-first: the brief at a glance (route map, budget split, dates ribbon), the original creative as
 * real assets, the scoring weights as a bar, and the Brand Kit's type specimens and logo lockups. Everything reads the
 * same API records as the ledgers below them.
 */

const SEGMENT_ROLES: RoleKey[] = ["desk", "lens", "studio", "lab", "launch", "pulse", "proof"];

// ---------- brief at a glance ----------

export function BriefGlance({ completeness, content, regions }: { completeness?: Brief["completeness"]; content: BriefContent; regions: Region[] | undefined }) {
  const [region, setRegion] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const origin = content.regions.origin;
  const targets = content.regions.targets;
  const name = (code: string) => regions?.find((r) => r.code === code)?.name ?? INDIA_TILES[code]?.name ?? code;
  const tiles: Record<string, TileDatum> = {};
  for (const t of targets) tiles[t] = { tone: "role", label: "Target region" };
  if (origin) tiles[origin] = { tone: "heat", value: 1, label: "Origin region" };
  const budget = content.budget;
  const dates = content.dates;
  const active = hover ?? region;

  const readout = (code: string | null) => {
    if (!code) {
      return (
        <p className="text-[13.5px] leading-relaxed text-ink-secondary">
          {origin ? <span className="font-medium text-ink">{name(origin)}</span> : "No origin"} to{" "}
          {targets.length ? targets.map(name).join(", ") : "no target regions yet"}. Hover or tab across the map for each region&apos;s languages and
          budget; click to pin one.
        </p>
      );
    }
    const langs = content.languages[code] ?? [];
    const scripts = content.scripts[code] ?? [];
    const amount = budget?.by_region[code];
    return (
      <div key={code} className="space-y-2">
        <p className="flex flex-wrap items-baseline gap-2">
          <span className="type-title text-[22px] text-ink">{name(code)}</span>
          <span className="type-meta">{code === origin ? "Origin" : "Target"}</span>
        </p>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-ink-muted">Languages</dt>
          <dd className="text-ink-body">{langs.length ? langs.map((l) => `${languageName(l)} (${l})`).join(", ") : "None set"}</dd>
          <dt className="text-ink-muted">Scripts</dt>
          <dd className="text-ink-body">{scripts.length ? scripts.map(scriptName).join(", ") : "None set"}</dd>
          {budget && (
            <>
              <dt className="text-ink-muted">Budget</dt>
              <dd className="text-ink-body tabular-nums">{amount !== undefined ? formatMoney(budget.currency, amount) : "Not assigned"}</dd>
            </>
          )}
        </dl>
      </div>
    );
  };

  return (
    <div className="grid gap-4 lg:grid-cols-12">
      <section aria-labelledby="g-brief" className="bento tint-desk flex flex-col gap-4 lg:col-span-4">
        <h2 id="g-brief" className="text-[15px] font-semibold text-ink">
          The brief at a glance
        </h2>
        {completeness ? (
          <div className="flex items-center gap-4">
            <RingGauge value={completeness.filled} max={completeness.required} label="Required brief parts filled" caption="parts" size={96} tone="desk" />
            <p className="text-[13.5px] leading-relaxed text-ink-body">
              {completeness.complete ? "Every required part is filled; every workspace reads this brief." : `${completeness.required - completeness.filled} required parts are still missing.`}
            </p>
          </div>
        ) : (
          <p className="text-[13.5px] leading-relaxed text-ink-body">An earlier version of the brief, shown as it was saved.</p>
        )}
        {content.channels.length > 0 && (
          <ul aria-label="Channels" className="flex flex-wrap gap-1.5">
            {content.channels.map((ch) => (
              <li key={ch.id} className="rounded-full bg-surface-raised px-2.5 py-1 text-[12.5px] font-medium text-ink shadow-clay">
                {ch.name}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="g-route" className="bento lg:col-span-8">
        <h2 id="g-route" className="mb-3 text-[15px] font-semibold text-ink">
          From origin to target regions
        </h2>
        <div className="grid items-start gap-5 sm:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <IndiaTileMap
            ariaLabel="Origin and target regions"
            tiles={tiles}
            selected={region}
            onSelect={setRegion}
            color={roleColor("desk", true)}
            onHover={setHover}
          />
          <div aria-live="polite" className="min-w-0 rounded-xl bg-surface-muted/50 p-4 shadow-well">
            {readout(active)}
          </div>
        </div>
      </section>

      {budget && (
        <section aria-labelledby="g-budget" className="bento lg:col-span-7">
          <h2 id="g-budget" className="mb-1 inline-flex items-center gap-2 text-[15px] font-semibold text-ink">
            <Wallet aria-hidden className="size-4 text-ink-muted" />
            Budget split
          </h2>
          <p className="type-title text-[30px] text-ink">
            <CountUp value={budget.total} format={(n) => formatMoney(budget.currency, Math.round(n))} />
          </p>
          <BudgetBar budget={budget} name={name} active={active} onHover={setHover} onPick={(code) => setRegion((r) => (r === code ? null : code))} />
          {(budget.sample || budget.note) && <p className="mt-2 text-[12px] text-ink-muted">{budget.note ?? "Source: sample figures"}</p>}
        </section>
      )}

      {dates && (
        <section aria-labelledby="g-dates" className={cn("bento", budget ? "lg:col-span-5" : "lg:col-span-12")}>
          <h2 id="g-dates" className="mb-1 inline-flex items-center gap-2 text-[15px] font-semibold text-ink">
            <CalendarRange aria-hidden className="size-4 text-ink-muted" />
            Campaign dates
          </h2>
          <p className="text-[13.5px] text-ink-body">
            {dayLabel(dates.start)} to {dayLabel(dates.end)} · <CountUp value={daysBetween(dates.start, dates.end)} className="font-semibold text-ink" /> days
          </p>
          <TimelineRibbon
            className="mt-3"
            ariaLabel="Campaign dates and key moments"
            scale="time"
            formatAt={(iso) => dayLabel(iso.slice(0, 10))}
            items={[
              { id: "start", at: `${dates.start}T00:00:00Z`, label: "Campaign starts", color: "var(--pop)" },
              ...dates.key_moments.map((m) => ({
                id: m.id,
                at: `${m.date}T12:00:00Z`,
                label: m.name,
                detail: m.region_codes.length ? m.region_codes.map(name).join(", ") : "All regions",
                color: roleColor("lens", true),
              })),
              { id: "end", at: `${dates.end}T23:00:00Z`, label: "Campaign ends", color: "var(--pop)" },
            ]}
          />
        </section>
      )}
    </div>
  );
}

function BudgetBar({
  budget,
  name,
  active,
  onHover,
  onPick,
}: {
  budget: NonNullable<BriefContent["budget"]>;
  name: (code: string) => string;
  active: string | null;
  onHover: (code: string | null) => void;
  onPick: (code: string) => void;
}) {
  const entries = Object.entries(budget.by_region);
  const allocated = entries.reduce((s, [, v]) => s + v, 0);
  const rest = Math.max(0, budget.total - allocated);
  const share = (v: number) => (budget.total ? Math.round((v / budget.total) * 100) : 0);
  const shown = active ? entries.find(([c]) => c === active) : null;
  if (entries.length === 0) return <p className="mt-2 text-[13px] text-ink-secondary">No amount is assigned to a region yet.</p>;
  return (
    <div className="mt-3 space-y-2.5">
      <div role="group" aria-label="Budget by region" className="grow-x flex h-12 gap-1 rounded-xl bg-surface-muted/60 p-1 shadow-well">
        {entries.map(([code, amount], i) => (
          <button
            key={code}
            type="button"
            aria-pressed={active === code}
            aria-label={`${name(code)}: ${formatMoney(budget.currency, amount)}, ${share(amount)}% of the total`}
            onPointerEnter={() => onHover(code)}
            onPointerLeave={() => onHover(null)}
            onFocus={() => onHover(code)}
            onBlur={() => onHover(null)}
            onClick={() => onPick(code)}
            className={cn(
              "min-w-0 overflow-hidden rounded-lg px-2 text-left font-mono text-[11px] text-[#2b2233] transition-[translate,box-shadow,opacity] duration-200 ease-out",
              active && active !== code ? "opacity-55" : "opacity-100",
              active === code && "-translate-y-0.5 shadow-clay",
            )}
            style={{ flexGrow: amount, flexBasis: 0, backgroundColor: roleColor(SEGMENT_ROLES[i % SEGMENT_ROLES.length]) } as CSSProperties}
          >
            {code.slice(3)}
          </button>
        ))}
        {rest > 0.005 && <span aria-hidden className="rounded-lg bg-[repeating-linear-gradient(135deg,var(--border)_0_4px,transparent_4px_8px)]" style={{ flexGrow: rest, flexBasis: 0 }} />}
      </div>
      <p className="min-h-5 text-[13px] text-ink-secondary">
        {shown ? (
          <>
            <span className="font-medium text-ink">{name(shown[0])}</span>: <span className="tabular-nums">{formatMoney(budget.currency, shown[1])}</span>, {share(shown[1])}% of the total
          </>
        ) : rest > 0.005 ? (
          `${formatMoney(budget.currency, rest)} of the total is not assigned to a region.`
        ) : (
          "Hover or tab across the bar to read each region's share; click to pin it on the map."
        )}
      </p>
    </div>
  );
}

// ---------- original creative as real assets ----------

export function CreativeAssets({ campaign, lang }: { campaign: Campaign; lang?: string }) {
  const creatives = useCreatives(campaign.id);
  const list = creatives.data ?? [];
  const stills = list.filter((c) => c.kind === "image");
  const film = list.find((c) => c.kind === "video");
  const scenes = useScenes(film?.id ?? "", film?.current_run_id ?? null);
  const frames = (scenes.data ?? []).filter((s) => s.keyframe_url).sort((a, b) => a.position - b.position);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const xray = (id: string) => `${workspaceHref(campaign.id, "studio")}/xray?creative=${id}`;

  if (creatives.isPending) {
    return (
      <div aria-hidden className="grid gap-4 lg:grid-cols-12">
        <div className="dough h-96 rounded-[18px] lg:col-span-4" />
        <div className="dough h-96 rounded-[18px] lg:col-span-8" />
      </div>
    );
  }
  if (list.length === 0) {
    return (
      <EmptyState
        illustration={<EmptyIllustration kind="film" />}
        title="No creative files yet"
        description="Upload the original key visual or film in Creative X-Ray; it is decomposed into scenes and keyframes that every workspace can point at."
        action={
          <Link href={`${workspaceHref(campaign.id, "studio")}/xray`} className="inline-flex items-center gap-1 text-[13.5px] font-medium text-rose hover:underline">
            Open Creative X-Ray
            <ArrowUpRight aria-hidden className="size-4" />
          </Link>
        }
      />
    );
  }

  const scene = frames.find((s) => s.id === (hovered ?? pinned)) ?? frames[0];
  return (
    <div className="grid gap-4 lg:grid-cols-12">
      {stills.map((s) => (
        <TiltCard key={s.id} as="section" aria-label={s.label} max={4} className="bento tint-studio flex flex-col gap-3 lg:col-span-4">
          <div className="relative aspect-4/5 overflow-hidden rounded-[14px] bg-surface-muted shadow-clay">
            <ApiImage path={s.thumbnail_url} alt={s.label} className="size-full" />
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-[14px] font-semibold text-ink">{s.label}</p>
            <Link href={xray(s.id)} className="group inline-flex items-center gap-1 text-[13px] font-medium text-rose">
              X-Ray
              <ArrowUpRight aria-hidden className="size-3.5 transition-[translate] duration-200 group-hover:translate-x-0.5" />
            </Link>
          </div>
        </TiltCard>
      ))}
      {film && (
        <section aria-labelledby="film-title" className={cn("bento", stills.length ? "lg:col-span-8" : "lg:col-span-12")}>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="film-title" className="inline-flex items-center gap-2 text-[15px] font-semibold text-ink">
              <Film aria-hidden className="size-4 text-ink-muted" />
              {film.label}
            </h2>
            <Link href={xray(film.id)} className="group inline-flex items-center gap-1 text-[13px] font-medium text-rose">
              Open in Creative X-Ray
              <ArrowUpRight aria-hidden className="size-3.5 transition-[translate] duration-200 group-hover:translate-x-0.5" />
            </Link>
          </div>
          {frames.length === 0 ? (
            <div className="grid place-items-center gap-2 rounded-xl bg-surface-muted/60 px-4 py-10 text-center text-[13px] text-ink-secondary">
              <ImageOff aria-hidden className="size-5 text-ink-muted" />
              {film.current_run_id ? "Reading the scenes…" : "The film has not been analysed yet; X-Ray splits it into scenes and keyframes."}
            </div>
          ) : (
            <div className="grid items-start gap-5 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
              <figure className="relative mx-auto w-full max-w-[13rem]">
                <div className="relative aspect-9/16 overflow-hidden rounded-[14px] bg-black shadow-float">
                  {scene?.keyframe_url && <ApiImage key={scene.keyframe_url} path={scene.keyframe_url} alt={`Scene ${scene.position + 1}`} className="size-full" />}
                  {scene && <span className="absolute top-2 left-2 rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[11px] text-white tabular-nums">{clock(scene.start_ms)}</span>}
                </div>
              </figure>
              <div className="min-w-0 space-y-3">
                {scene && (
                  <div key={scene.id} className="reveal space-y-1.5">
                    <p className="flex flex-wrap items-baseline gap-2">
                      <span className="type-title text-[20px] text-ink">Scene {scene.position + 1}</span>
                      <span className="type-meta tabular-nums">
                        {clock(scene.start_ms)} to {scene.end_ms !== null ? clock(scene.end_ms) : "end"}
                      </span>
                    </p>
                    {scene.on_screen_text.slice(0, 2).map((t, i) => (
                      <p key={i} lang={film.language ?? lang} className="text-[15px] text-ink-body">
                        {t.text}
                      </p>
                    ))}
                  </div>
                )}
                <FilmStrip
                  ariaLabel={`Scenes of ${film.label}`}
                  preview={false}
                  selectedId={pinned}
                  onSelect={(id) => setPinned((p) => (p === id ? null : id))}
                  onActiveChange={setHovered}
                  frames={frames.map((s) => ({ id: s.id, label: `Scene ${s.position + 1}`, at: clock(s.start_ms), media: <ApiImage path={s.keyframe_url} alt="" className="size-full" /> }))}
                />
                <p className="text-[12.5px] text-ink-secondary">Move along the strip to scrub the film; click a scene to hold it.</p>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------- scoring weights as a bar ----------

export function WeightsBar({ criteria }: { criteria: Campaign["evaluation_criteria"] }) {
  const [hover, setHover] = useState<string | null>(null);
  const total = WEIGHT_FIELDS.reduce((s, f) => s + criteria[f.key], 0);
  const active = WEIGHT_FIELDS.find((f) => f.key === hover);
  return (
    <div className="space-y-3">
      <div
        role="img"
        aria-label={`Scoring weights: ${WEIGHT_FIELDS.map((f) => `${f.label} ${criteria[f.key].toFixed(2)}`).join(", ")}; total ${total.toFixed(3)}`}
        className="grow-x flex h-14 gap-1 rounded-xl bg-surface-muted/60 p-1 shadow-well"
      >
        {WEIGHT_FIELDS.map((f, i) => (
          <span
            key={f.key}
            onPointerEnter={() => setHover(f.key)}
            onPointerLeave={() => setHover(null)}
            className={cn(
              "flex min-w-0 flex-col justify-center overflow-hidden rounded-lg px-2.5 text-[#2b2233] transition-[opacity,translate] duration-200",
              hover && hover !== f.key ? "opacity-55" : "opacity-100",
              hover === f.key && "-translate-y-0.5",
            )}
            style={{ flexGrow: criteria[f.key], flexBasis: 0, backgroundColor: roleColor(SEGMENT_ROLES[(i + 1) % SEGMENT_ROLES.length]) }}
          >
            <span className="truncate text-[11.5px] font-semibold">{f.label}</span>
            <span className="font-mono text-[11px] tabular-nums">{criteria[f.key].toFixed(2)}</span>
          </span>
        ))}
      </div>
      <p className="min-h-5 text-[13px] text-ink-secondary">
        {active ? (
          <>
            <span className="font-medium text-ink">{active.label}</span> weighs <span className="tabular-nums">{criteria[active.key].toFixed(2)}</span>: {active.help}
          </>
        ) : (
          <>
            Weights total <span className="tabular-nums text-ink">{total.toFixed(3)}</span> and are never rescaled. Hover a part for what it measures.
          </>
        )}
      </p>
      <dl className="ledger-rules rounded-xl border border-border bg-surface">
        {WEIGHT_FIELDS.map((f) => (
          <div key={f.key} className="grid gap-1 px-4 py-2 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">{f.label}</dt>
            <dd className="type-ledger text-[13.5px] text-ink-body tabular-nums">
              {criteria[f.key].toFixed(2)} <span className="text-ink-muted">· {f.help}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------- Brand Kit: type specimens and logo lockups ----------

type KitFont = KitDesign["fonts"][number];

const SPECIMEN: Record<string, { text: string; lang: string }> = {
  Latn: { text: "Aa Gg Rr 0123", lang: "en" },
  Deva: { text: "अ आ क ख देवनागरी", lang: "hi" },
  Taml: { text: "அ ஆ க ங தமிழ்", lang: "ta" },
  Mlym: { text: "അ ആ ക ഖ മലയാളം", lang: "ml" },
  Beng: { text: "অ আ ক খ বাংলা", lang: "bn" },
  Telu: { text: "అ ఆ క ఖ తెలుగు", lang: "te" },
  Knda: { text: "ಅ ಆ ಕ ಖ ಕನ್ನಡ", lang: "kn" },
  Gujr: { text: "અ આ ક ખ ગુજરાતી", lang: "gu" },
  Guru: { text: "ਅ ਆ ਕ ਖ ਗੁਰਮੁਖੀ", lang: "pa" },
  Orya: { text: "ଅ ଆ କ ଖ ଓଡ଼ିଆ", lang: "or" },
};

const requested = new Set<string>();

/** Loads a Google Fonts family for a specimen (only when the Brand Kit names Google Fonts as its source). */
function useGoogleFont(font: KitFont) {
  const google = Boolean(font.source && /fonts\.google\.com/.test(font.source));
  useEffect(() => {
    if (!google || requested.has(font.family)) return;
    requested.add(font.family);
    const weights = font.weights.length ? `:wght@${[...font.weights].sort((a, b) => a - b).join(";")}` : "";
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(font.family).replace(/%20/g, "+")}${weights}&display=swap`;
    document.head.appendChild(link);
  }, [google, font.family, font.weights]);
}

export function TypeSpecimen({ font, sample }: { font: KitFont; sample?: string | null }) {
  useGoogleFont(font);
  const weights = font.weights.length ? font.weights : [400];
  const [weight, setWeight] = useState(String(weights[0]));
  const [size, setSize] = useState(44);
  const script = font.scripts[0] ?? "Latn";
  const spec = SPECIMEN[script] ?? SPECIMEN.Latn;
  const family = { fontFamily: `"${font.family}", var(--font-sans)`, fontWeight: Number(weight) };
  return (
    <TiltCard as="li" max={3} className="bento flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[14px] font-semibold text-ink">
          {font.source ? (
            <a href={font.source} target="_blank" rel="noopener noreferrer" className="hover:text-rose hover:underline">
              {font.family}
            </a>
          ) : (
            font.family
          )}
        </p>
        <span className="type-meta">{font.scripts.map(scriptName).join(", ")}</span>
      </div>
      <p lang={spec.lang} className="min-h-[1.3em] overflow-hidden leading-[1.25] break-words text-ink" style={{ ...family, fontSize: size }}>
        {script === "Latn" && sample ? sample : spec.text}
      </p>
      <div className="mt-auto flex flex-wrap items-center gap-3">
        {weights.length > 1 && (
          <ChipToggleGroup size="sm" ariaLabel={`${font.family} weight`} value={weight} onChange={setWeight} options={weights.map((w) => ({ value: String(w), label: String(w) }))} />
        )}
        <label className="flex min-w-0 flex-1 items-center gap-2 text-[12px] text-ink-secondary">
          <span className="shrink-0">Size</span>
          <input type="range" min={20} max={72} value={size} onChange={(e) => setSize(Number(e.target.value))} aria-label={`${font.family} specimen size`} className="min-w-0 flex-1 accent-[var(--pop)]" />
          <span className="w-9 shrink-0 text-right tabular-nums">{size}px</span>
        </label>
      </div>
      {font.role && <p className="text-[12.5px] leading-relaxed text-ink-secondary">{font.role}</p>}
    </TiltCard>
  );
}

type Lockup = KitDesign["logo"]["lockups"][number];

export function LockupCard({ lockup, kitName, colours }: { lockup: Lockup; kitName: string; colours: KitDesign["colours"] }) {
  const backs = [{ id: "check", name: "Transparent", hex: null as string | null }, ...colours.slice(0, 5).map((c) => ({ id: c.id, name: c.name, hex: c.hex }))];
  const [back, setBack] = useState("check");
  const current = backs.find((b) => b.id === back) ?? backs[0];
  return (
    <TiltCard as="li" max={4} className="bento flex flex-col gap-3 p-3.5">
      <div
        className={cn(
          "grid h-28 place-items-center overflow-hidden rounded-xl p-3 transition-[background-color] duration-300",
          !current.hex && "bg-[repeating-conic-gradient(var(--color-surface-muted)_0%_25%,var(--color-surface)_0%_50%)] bg-size-[16px_16px]",
        )}
        style={current.hex ? { backgroundColor: current.hex } : undefined}
      >
        {lockup.asset_id ? (
          <ApiImage path={`/api/v1/assets/${lockup.asset_id}/content`} alt={`${kitName} logo, ${lockup.id} lockup on ${current.name.toLowerCase()}`} fit="contain" className="max-h-full w-full" />
        ) : (
          <span className="flex flex-col items-center gap-1 text-center text-[11.5px] text-ink-muted">
            <ImageOff aria-hidden className="size-5" />
            Not uploaded
            {lockup.source_path && <span className="font-mono text-[10.5px] break-all">{lockup.source_path}</span>}
          </span>
        )}
      </div>
      <div role="radiogroup" aria-label={`Preview the ${lockup.id} lockup on`} className="flex flex-wrap items-center gap-1.5">
        {backs.map((b) => (
          <button
            key={b.id}
            type="button"
            role="radio"
            aria-checked={back === b.id}
            aria-label={b.name}
            title={b.name}
            onClick={() => setBack(b.id)}
            className={cn(
              "size-6 rounded-full border border-border shadow-clay transition-[scale] duration-150 hover:scale-110",
              back === b.id && "ring-2 ring-pop ring-offset-2 ring-offset-surface",
              !b.hex && "bg-[repeating-conic-gradient(var(--color-surface-muted)_0%_25%,var(--color-surface-raised)_0%_50%)] bg-size-[8px_8px]",
            )}
            style={b.hex ? { backgroundColor: b.hex } : undefined}
          />
        ))}
      </div>
      <div>
        <p className="text-[13.5px] font-medium text-ink capitalize">{lockup.id}</p>
        <p className="text-[12.5px] text-ink-secondary">{lockup.use}</p>
      </div>
    </TiltCard>
  );
}
