"use client";

import { ArrowUpRight, Bot, Calculator, Film, GitCompareArrows, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import {
  ApiImage,
  ChipToggleGroup,
  CountUp,
  FilmStrip,
  INDIA_TILES,
  IndiaTileMap,
  RingGauge,
  RoleMark,
  Stagger,
  TiltCard,
  TimelineRibbon,
  VerdictStamp,
  roleColor,
  type TileDatum,
} from "@/components/creative";
import { ModeBadge, Tag } from "@/components/evidence/badges";
import { WORKSPACES, workspaceHref, type WorkspaceKey } from "@/components/shell/workspaces";
import { ErrorState } from "@/components/states";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import { useCreatives, useScenes, type CreativeSummary } from "@/features/xray/api";
import { clock } from "@/features/xray/parts";
import type { ProjectSummary, Run } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { REQUIRED_LABEL, type TodayCampaign, type TodayConflict, type TodayEvent, type TodayNextAction } from "./types";
import type { DirectoryCampaign } from "./use-campaign-directory";

/*
 * Today's bento tiles. Every number, verdict, image and event comes from a saved record the API returned; the tiles only
 * arrange, animate and filter it.
 */

export const REQUIRED_PARTS = Object.keys(REQUIRED_LABEL).length;

/** Does a free-text line mention a region by name? Used for the "click a state to filter" interaction. */
export const mentions = (text: string | null | undefined, name: string | null) => !name || Boolean(text && text.toLowerCase().includes(name.toLowerCase()));

function TileHead({ id, title, meta, children }: { id: string; title: ReactNode; meta?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <h2 id={id} className="text-[15px] font-semibold text-ink">
        {title}
      </h2>
      {meta && <span className="type-meta">{meta}</span>}
      {children}
    </div>
  );
}

/** "Showing what mentions Kerala · Clear": the visible way back from a map filter. */
function RegionFilterNote({ name, onClear }: { name: string | null; onClear: () => void }) {
  if (!name) return null;
  return (
    <p className="mb-2.5 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-secondary">
      Showing what mentions <span className="font-medium text-ink">{name}</span>
      <button type="button" onClick={onClear} className="rounded-md px-1.5 py-0.5 font-medium text-rose hover:bg-surface-muted">
        Clear
      </button>
    </p>
  );
}

// ---------- hero: the most recent campaign, imagery first ----------

function Poster({ campaign, still, film, frame }: { campaign: DirectoryCampaign; still?: CreativeSummary; film?: CreativeSummary; frame?: { url: string; at: string; label: string } | null }) {
  const content = campaign.current_version.content;
  const path = frame?.url ?? still?.thumbnail_url ?? film?.thumbnail_url ?? null;
  const caption = frame ? `${frame.label} · ${frame.at}` : still ? still.label : film ? film.label : null;
  return (
    <figure className="relative">
      <div className="relative aspect-4/5 overflow-hidden rounded-[14px] bg-surface-muted shadow-clay">
        {path ? (
          <ApiImage key={path} path={path} alt={caption ?? campaign.name} className="size-full" />
        ) : (
          // No creative uploaded yet: the copy itself is the poster.
          <div className="creative-mat flex size-full flex-col justify-end gap-2 p-5">
            {content.headline && <p className="type-title text-[22px] leading-tight">{content.headline}</p>}
            {content.call_to_action && <p className="text-[13px] font-semibold opacity-80">{content.call_to_action}</p>}
          </div>
        )}
        {frame && <span className="absolute top-2.5 left-2.5 rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[11px] text-white tabular-nums">{frame.at}</span>}
      </div>
      {caption && <figcaption className="mt-2 truncate text-[12px] text-ink-secondary">{caption}</figcaption>}
    </figure>
  );
}

export function HeroCampaign({ campaign, card, run, className }: { campaign: DirectoryCampaign; card?: TodayCampaign; run?: Run; className?: string }) {
  const creatives = useCreatives(campaign.id);
  const list = creatives.data ?? [];
  const still = list.find((c) => c.kind === "image" && c.thumbnail_url);
  const film = list.find((c) => c.kind === "video");
  const scenes = useScenes(film?.id ?? "", film?.current_run_id ?? null);
  const frames = (scenes.data ?? []).filter((s) => s.keyframe_url).sort((a, b) => a.position - b.position);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const shownId = hovered ?? pinned;
  const shown = frames.find((s) => s.id === shownId);
  const filled = card ? REQUIRED_PARTS - card.brief_missing.length : null;
  const regions = campaign.target_markets.map((m) => m.display_name);

  return (
    <TiltCard as="section" aria-labelledby="hero-title" max={2.5} className={cn("bento tint-desk", className)}>
      <div className="grid gap-5 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,16.5rem)_minmax(0,1fr)]">
        <Poster
          campaign={campaign}
          still={still}
          film={film}
          frame={shown ? { url: shown.keyframe_url!, at: clock(shown.start_ms), label: `Scene ${shown.position + 1} of ${frames.length}` } : null}
        />
        <div className="flex min-w-0 flex-col gap-4">
          <div>
            <p className="flex flex-wrap items-center gap-x-2 text-[12.5px] text-ink-secondary">
              {campaign.brand.name}
              {campaign.brand.mode === "demo" && <ModeBadge mode="demo" />}
            </p>
            <h2 id="hero-title" className="type-title mt-1 text-[24px] text-ink sm:text-[28px]">
              <Link href={workspaceHref(campaign.id, "desk")} className="hover:text-rose">
                {campaign.name}
              </Link>
            </h2>
            {campaign.objective && <p className="mt-2 line-clamp-3 max-w-[62ch] text-[14px] leading-relaxed text-ink-body">{campaign.objective}</p>}
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            {filled !== null && <RingGauge value={filled} max={REQUIRED_PARTS} label="Required brief parts filled" caption="brief" size={78} tone="desk" />}
            <dl className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
              <dt className="text-ink-muted">Regions</dt>
              <dd className="min-w-0 text-ink-body">{regions.length ? regions.join(", ") : "None set"}</dd>
              <dt className="text-ink-muted">Last run</dt>
              <dd>{run ? <RunStatusBadge status={run.status} /> : <span className="text-ink-secondary">No runs yet</span>}</dd>
              <dt className="text-ink-muted">Updated</dt>
              <dd className="text-ink-body" title={formatDateTime(campaign.updated_at)}>
                {formatRelative(campaign.updated_at)}
              </dd>
            </dl>
          </div>

          {film && frames.length > 1 && (
            <div className="space-y-1.5">
              <p className="flex items-center gap-1.5 text-[12.5px] text-ink-secondary">
                <Film aria-hidden className="size-3.5" />
                {film.label}. Move along the strip to scrub the poster; click a scene to keep it there.
              </p>
              <FilmStrip
                ariaLabel={`Scenes of ${film.label}`}
                preview={false}
                selectedId={pinned}
                onSelect={(id) => setPinned((p) => (p === id ? null : id))}
                onActiveChange={setHovered}
                frames={frames.map((s) => ({
                  id: s.id,
                  label: `Scene ${s.position + 1}`,
                  at: clock(s.start_ms),
                  media: <ApiImage path={s.keyframe_url} alt="" className="size-full" />,
                }))}
              />
            </div>
          )}

          <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2 text-[13.5px] font-medium">
            <Link href={workspaceHref(campaign.id, "desk")} className="group inline-flex items-center gap-1 text-rose">
              Open Campaign Desk
              <ArrowUpRight aria-hidden className="size-4 transition-[translate] duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>
            {film && (
              <Link href={`${workspaceHref(campaign.id, "studio")}/xray?creative=${film.id}`} className="group inline-flex items-center gap-1 text-ink-secondary hover:text-ink">
                Open in Creative X-Ray
                <ArrowUpRight aria-hidden className="size-4 transition-[translate] duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </Link>
            )}
          </div>
        </div>
      </div>
    </TiltCard>
  );
}

// ---------- readiness: verdicts stamped on the map ----------

export function ReadinessTile({
  campaigns,
  cards,
  region,
  onRegion,
  pending,
  className,
}: {
  campaigns: DirectoryCampaign[];
  cards: Map<string, TodayCampaign>;
  region: string | null;
  onRegion: (code: string | null) => void;
  pending: boolean;
  className?: string;
}) {
  const withCards = campaigns.filter((c) => cards.has(c.id));
  const [chosen, setChosen] = useState<string | null>(null);
  const current = withCards.find((c) => c.id === chosen) ?? withCards.find((c) => cards.get(c.id)!.readiness.length > 0) ?? withCards[0];
  const card = current ? cards.get(current.id) : undefined;
  const readiness = card?.readiness ?? [];
  const tiles: Record<string, TileDatum> = {};
  for (const code of card?.region_codes ?? []) tiles[code] = { tone: "role", label: "No verdict yet" };
  for (const r of readiness) tiles[r.region_code] = { tone: r.verdict, label: r.verdict === "go" ? "Go" : r.verdict === "fix" ? "Fix" : "Rethink" };
  const count = (v: "go" | "fix" | "rethink") => readiness.filter((r) => r.verdict === v).length;

  const readout = (code: string | null) => {
    const r = code ? readiness.find((x) => x.region_code === code) : null;
    if (code && r) {
      return (
        <div key={code} className="rounded-xl bg-surface-raised/80 px-3.5 py-3 shadow-clay">
          <div className="flex flex-wrap items-center gap-2.5">
            <VerdictStamp value={r.verdict} size="sm" />
            <span className="text-[14px] font-semibold text-ink">{r.region_name}</span>
          </div>
          <p className="mt-1.5 text-[13px] leading-relaxed text-ink-body">{r.main_reason}</p>
          <p className="type-meta mt-1">
            Rules {r.rule_version} · computed {formatRelative(r.computed_at)}
          </p>
        </div>
      );
    }
    if (code) {
      return (
        <div key={code} className="rounded-xl bg-surface-raised/80 px-3.5 py-3 text-[13px] text-ink-body shadow-clay">
          <span className="font-semibold text-ink">{INDIA_TILES[code]?.name ?? code}</span> is a target region with no readiness verdict yet.
        </div>
      );
    }
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {(["go", "fix", "rethink"] as const).map((v, i) => (
          <span key={v} className="inline-flex items-center gap-2">
            <VerdictStamp value={v} size="sm" delay={260 + readiness.length * 140 + i * 120} />
            <CountUp value={count(v)} className="type-title text-[22px] text-ink" />
          </span>
        ))}
      </div>
    );
  };

  return (
    <section aria-labelledby="readiness" className={cn("bento tint-launch", className)}>
      <TileHead id="readiness" title="Readiness by region">
        {withCards.length > 1 && (
          <ChipToggleGroup
            size="sm"
            ariaLabel="Campaign shown on the map"
            value={current?.id ?? ""}
            onChange={(id) => {
              setChosen(id);
              onRegion(null);
            }}
            options={withCards.slice(0, 4).map((c) => ({ value: c.id, label: c.name.length > 22 ? `${c.name.slice(0, 21)}…` : c.name }))}
          />
        )}
      </TileHead>
      {pending ? (
        <div aria-hidden className="dough aspect-8/7 rounded-xl" />
      ) : !card ? (
        <p className="text-[13.5px] text-ink-secondary">Readiness appears here once a campaign has target regions and Launch Room has computed a verdict.</p>
      ) : (
        <>
          <IndiaTileMap
            ariaLabel={`Readiness by region for ${current?.name}`}
            tiles={tiles}
            selected={region}
            onSelect={onRegion}
            color={roleColor("launch", true)}
            animate
            renderReadout={readout}
          />
          <p className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-ink-secondary">
            <span>{readiness.length ? "Hover a state for its main reason; click it to filter the lists." : "No verdict computed yet."}</span>
            {current && (
              <Link href={workspaceHref(current.id, "launch")} className="group inline-flex items-center gap-1 font-medium text-rose">
                Launch Room
                <ArrowUpRight aria-hidden className="size-3.5 transition-[translate] duration-200 group-hover:translate-x-0.5" />
              </Link>
            )}
          </p>
        </>
      )}
    </section>
  );
}

// ---------- next actions ----------

export function NextActionsTile({
  actions,
  regionName,
  onClearRegion,
  pending,
  error,
  onRetry,
  className,
}: {
  actions: { a: TodayNextAction; c: TodayCampaign }[];
  regionName: string | null;
  onClearRegion: () => void;
  pending: boolean;
  error: unknown;
  onRetry: () => void;
  className?: string;
}) {
  const [ws, setWs] = useState("all");
  const inRegion = actions.filter(({ a }) => mentions(`${a.title} ${a.reason}`, regionName));
  const present = [...new Set(inRegion.map(({ a }) => a.workspace))];
  const shown = inRegion.filter(({ a }) => ws === "all" || a.workspace === ws);
  return (
    <section id="next" aria-labelledby="next-title" className={cn("bento scroll-mt-24", className)}>
      <TileHead id="next-title" title="Next actions">
        {present.length > 1 && (
          <ChipToggleGroup
            size="sm"
            ariaLabel="Filter next actions by workspace"
            value={present.includes(ws as WorkspaceKey) ? ws : "all"}
            onChange={setWs}
            options={[{ value: "all", label: "All", count: inRegion.length }, ...present.map((k) => ({ value: k, label: WORKSPACES[k].label, count: inRegion.filter(({ a }) => a.workspace === k).length }))]}
          />
        )}
      </TileHead>
      <RegionFilterNote name={regionName} onClear={onClearRegion} />
      {pending ? (
        <div aria-hidden className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="dough h-14 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : shown.length === 0 ? (
        <p className="rounded-xl bg-surface-muted/60 px-4 py-3 text-[13.5px] text-ink-secondary">
          {regionName ? `Nothing waiting mentions ${regionName}.` : "Nothing is waiting. Every brief is complete and no run, verdict or evidence conflict needs a person."}
        </p>
      ) : (
        <Stagger as="ol" className="space-y-2">
          {shown.map(({ a, c }) => (
            <li key={a.id}>
              <Link
                href={workspaceHref(c.campaign_id, a.workspace)}
                className="group lift flex items-start gap-3 rounded-xl bg-surface-raised/70 px-3 py-2.5 shadow-clay hover:bg-surface-raised focus-visible:outline-offset-2"
              >
                <RoleMark workspace={a.workspace} size="sm" className="mt-0.5" />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-[14px] font-semibold text-ink">{a.title}</span>
                    {a.priority === 1 && (
                      <Tag className="border-warning/30 bg-warning-soft text-warning">
                        <UserRound aria-hidden />
                        Needs a person
                      </Tag>
                    )}
                  </span>
                  <span className="mt-0.5 block text-[12.5px] leading-relaxed text-ink-secondary">{a.reason}</span>
                  <span className="type-meta mt-0.5 block">
                    {WORKSPACES[a.workspace].label} · {c.name}
                  </span>
                </span>
                <ArrowUpRight aria-hidden className="mt-1 size-4 shrink-0 text-ink-muted transition-[translate,color] duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-rose" />
              </Link>
            </li>
          ))}
        </Stagger>
      )}
    </section>
  );
}

// ---------- open evidence conflicts: two receipts that disagree ----------

export function ConflictsTile({ conflicts, fallbackCampaign, regionName, pending, error, className }: { conflicts: TodayConflict[]; fallbackCampaign: string | null; regionName: string | null; pending: boolean; error: unknown; className?: string }) {
  const shown = conflicts.filter((c) => !regionName || c.region_name === regionName || mentions(c.reason, regionName));
  return (
    <section id="conflicts" aria-labelledby="conflicts-title" className={cn("bento tint-lens scroll-mt-24", className)}>
      <TileHead
        id="conflicts-title"
        title={
          <span className="inline-flex items-center gap-2">
            <GitCompareArrows aria-hidden className="size-4 text-ink-muted" />
            Open evidence conflicts
          </span>
        }
        meta={!pending && !error ? <CountUp value={shown.length} /> : undefined}
      />
      {pending ? (
        <div aria-hidden className="dough h-28 rounded-xl" />
      ) : error ? (
        <p className="text-[13px] text-danger">Could not read the conflicts.</p>
      ) : shown.length === 0 ? (
        <p className="rounded-xl bg-surface-raised/50 px-4 py-3 text-[13px] text-ink-secondary">
          {regionName ? `No open conflict mentions ${regionName}.` : "No open conflicts. Sources do not currently disagree on anything your campaigns rely on."}
        </p>
      ) : (
        <Stagger as="ol" className="space-y-3">
          {shown.map((c) => {
            const target = c.campaign_ids[0] ?? fallbackCampaign;
            const body = (
              <>
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-[14px] font-semibold text-ink">{c.region_name ?? "Workspace-wide"}</span>
                  <span className="type-meta">{c.status === "open" ? "Open" : "Review requested"}</span>
                </span>
                <span className="mt-0.5 block text-[12.5px] leading-relaxed text-ink-secondary">{c.reason}</span>
                {/* Two receipts that disagree; they part a little further when you reach for them. */}
                <span className="mt-2.5 grid grid-cols-2 gap-2">
                  {[
                    ["A", c.claim_a, "-rotate-2 group-hover:-translate-x-1 group-hover:-rotate-3"],
                    ["B", c.claim_b, "rotate-2 group-hover:translate-x-1 group-hover:rotate-3"],
                  ].map(([k, claim, motion]) => (
                    <span
                      key={k}
                      className={cn(
                        "receipt-corner block rounded-lg bg-surface-raised px-2.5 py-2 text-[12.5px] leading-snug text-ink-body shadow-clay transition-[rotate,translate] duration-300 ease-out",
                        motion,
                      )}
                    >
                      <span className="type-meta mb-0.5 block">Source {k}</span>
                      {claim}
                    </span>
                  ))}
                </span>
              </>
            );
            return (
              <li key={c.id}>
                {target ? (
                  <Link href={workspaceHref(target, "lens")} className="group block rounded-xl px-1 py-1 focus-visible:outline-offset-2">
                    {body}
                  </Link>
                ) : (
                  <div className="px-1 py-1">{body}</div>
                )}
              </li>
            );
          })}
        </Stagger>
      )}
    </section>
  );
}

// ---------- what changed: a scrubbable ribbon over the ledger ----------

const ACTOR: Record<NonNullable<TodayEvent["actor"]>, { label: string; Icon: typeof Bot }> = {
  user: { label: "A person", Icon: UserRound },
  ai: { label: "An AI run", Icon: Bot },
  system: { label: "Fixed rules", Icon: Calculator },
};

export function ChangesTile({
  events,
  regionName,
  onClearRegion,
  pending,
  error,
  onRetry,
  className,
}: {
  events: TodayEvent[];
  regionName: string | null;
  onClearRegion: () => void;
  pending: boolean;
  error: unknown;
  onRetry: () => void;
  className?: string;
}) {
  const router = useRouter();
  const [focus, setFocus] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const shown = events.filter((e) => mentions(`${e.title} ${e.detail ?? ""}`, regionName));
  const hrefOf = (e: TodayEvent) => (e.campaign_id ? workspaceHref(e.campaign_id, e.workspace) : null);
  const focusIndex = shown.findIndex((e) => e.id === focus);
  const visible = all || focusIndex >= 6 ? shown : shown.slice(0, 6);

  return (
    <section id="changes" aria-labelledby="changed" className={cn("bento scroll-mt-24", className)}>
      <TileHead id="changed" title="What changed" meta={shown.length ? `${shown.length} saved changes` : undefined} />
      <RegionFilterNote name={regionName} onClear={onClearRegion} />
      {pending ? (
        <div aria-hidden className="space-y-2">
          <div className="dough h-24 rounded-xl" />
          <div className="dough h-40 rounded-xl" />
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : shown.length === 0 ? (
        <p className="rounded-xl bg-surface-muted/60 px-4 py-3 text-[13.5px] text-ink-secondary">
          {regionName
            ? `No saved change mentions ${regionName}.`
            : "Nothing has changed yet. Saving a brief, uploading a creative, running a Quick Read or computing a readiness verdict will appear here, with who or what did it."}
        </p>
      ) : (
        <>
          {shown.length >= 3 && (
            <TimelineRibbon
              className="mb-4"
              ariaLabel="Saved changes, oldest to newest. Arrow keys move; Enter opens the change."
              value={focus}
              onChange={setFocus}
              onActivate={(id) => {
                const e = shown.find((x) => x.id === id);
                const href = e && hrefOf(e);
                if (href) router.push(href);
              }}
              items={shown.map((e) => ({ id: e.id, at: e.at, label: e.title, detail: WORKSPACES[e.workspace].label, color: roleColor(e.workspace, true) }))}
            />
          )}
          <ol className="ledger-rules clay-well overflow-hidden rounded-xl">
            {visible.map((e) => {
              const ws = WORKSPACES[e.workspace];
              const actor = e.actor ? ACTOR[e.actor] : null;
              const href = hrefOf(e);
              const body = (
                <>
                  <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full" style={{ backgroundColor: roleColor(e.workspace, true) }} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium text-ink">{e.title}</span>
                    {e.detail && <span className="block truncate text-[12.5px] text-ink-secondary">{e.detail}</span>}
                    <span className="type-meta mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span>{ws.label}</span>
                      <span aria-hidden>·</span>
                      <span className="truncate">{e.campaign_name ?? `${e.brand_name} brand`}</span>
                      {actor && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="inline-flex items-center gap-1">
                            <actor.Icon aria-hidden className="size-3" />
                            {actor.label}
                          </span>
                        </>
                      )}
                    </span>
                  </span>
                  <span className="type-meta shrink-0 pt-0.5" title={formatDateTime(e.at)}>
                    {formatRelative(e.at)}
                  </span>
                </>
              );
              const cls = cn("flex items-start gap-3 px-3.5 py-2.5 transition-colors duration-200", e.id === focus && "bg-pop-soft");
              return (
                <li key={e.id} aria-current={e.id === focus ? "true" : undefined}>
                  {href ? (
                    <Link href={href} onFocus={() => setFocus(e.id)} className={cn(cls, "hover:bg-surface-muted/60 focus-visible:-outline-offset-2")}>
                      {body}
                    </Link>
                  ) : (
                    <div className={cls}>{body}</div>
                  )}
                </li>
              );
            })}
          </ol>
          {shown.length > 6 && focusIndex < 6 && (
            <button type="button" onClick={() => setAll((v) => !v)} className="mt-2.5 rounded-md px-1.5 py-1 text-[13px] font-medium text-rose hover:bg-surface-muted">
              {all ? "Show the latest 6" : `Show all ${shown.length}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

// ---------- recent runs ----------

export function RunsTile({ runs, pending, className }: { runs: { run: Run; brand: ProjectSummary }[]; pending: boolean; className?: string }) {
  const [status, setStatus] = useState("all");
  const statuses = [...new Set(runs.map(({ run }) => run.status))];
  const shown = runs.filter(({ run }) => status === "all" || run.status === status).slice(0, 10);
  const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
  return (
    <section id="runs" aria-labelledby="recent-runs" className={cn("bento tint-proof scroll-mt-24", className)}>
      <TileHead id="recent-runs" title="Recent runs">
        {statuses.length > 1 && (
          <ChipToggleGroup
            size="sm"
            ariaLabel="Filter runs by state"
            value={statuses.includes(status as Run["status"]) ? status : "all"}
            onChange={setStatus}
            options={[{ value: "all", label: "All", count: runs.length }, ...statuses.map((s) => ({ value: s, label: label(s), count: runs.filter(({ run }) => run.status === s).length }))]}
          />
        )}
      </TileHead>
      {pending ? (
        <div aria-hidden className="dough h-40 rounded-xl" />
      ) : runs.length === 0 ? (
        <p className="rounded-xl bg-surface-raised/50 px-4 py-3 text-[13px] text-ink-secondary">No runs yet. Runs appear here as soon as any workspace starts one.</p>
      ) : (
        <ol className="ledger-rules clay-well overflow-hidden rounded-xl">
          {shown.map(({ run, brand }) => {
            const meta = RUN_TYPE_META[run.run_type];
            return (
              <li key={run.id}>
                <Link
                  href={sectionHref(run.project_id, meta.segment, run.campaign_id)}
                  className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 px-3.5 py-2.5 transition-colors duration-200 hover:bg-surface-raised/60 focus-visible:-outline-offset-2"
                >
                  <span className="truncate text-[13.5px] font-medium text-ink">{meta.label}</span>
                  <RunStatusBadge status={run.status} />
                  <span className="truncate text-[12px] text-ink-muted">
                    {brand.name}
                    {run.mode === "demo" && " · demo fixture"}
                  </span>
                  <span className="type-meta text-right" title={formatDateTime(run.created_at)}>
                    {formatRelative(run.created_at)}
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// ---------- more campaigns ----------

function CampaignCard({ campaign, card, run }: { campaign: DirectoryCampaign; card?: TodayCampaign; run?: Run }) {
  const creatives = useCreatives(campaign.id);
  const thumb = (creatives.data ?? []).find((c) => c.thumbnail_url)?.thumbnail_url ?? null;
  const filled = card ? REQUIRED_PARTS - card.brief_missing.length : null;
  return (
    <TiltCard as="li" className="bento flex w-[17rem] shrink-0 snap-start flex-col gap-3 p-3.5">
      <div className="relative aspect-video overflow-hidden rounded-xl bg-surface-muted">
        {thumb ? (
          <ApiImage path={thumb} alt="" className="size-full" />
        ) : (
          <div className="creative-mat flex size-full items-end p-3">
            <span className="type-title line-clamp-2 text-[16px]">{campaign.current_version.content.headline ?? campaign.name}</span>
          </div>
        )}
      </div>
      <div className="min-w-0">
        <h3 className="truncate text-[14px] font-semibold text-ink">
          <Link href={workspaceHref(campaign.id, "desk")} className="after:absolute after:inset-0 hover:text-rose">
            {campaign.name}
          </Link>
        </h3>
        <p className="mt-0.5 flex items-center gap-2 truncate text-[12px] text-ink-secondary">
          {campaign.brand.name}
          {campaign.brand.mode === "demo" && <ModeBadge mode="demo" />}
        </p>
      </div>
      <div className="flex items-center gap-3">
        {filled !== null && <RingGauge value={filled} max={REQUIRED_PARTS} label="Required brief parts filled" size={46} tone="desk" />}
        <div className="flex min-w-0 flex-wrap gap-1">
          {card?.readiness.slice(0, 4).map((r) => (
            <span key={r.region_code} title={`${r.region_name}: ${r.main_reason}`}>
              <VerdictStamp value={r.verdict} size="sm" animate={false} tilt={0} />
            </span>
          ))}
          {card && card.readiness.length === 0 && <span className="text-[12px] text-ink-secondary">No verdict yet</span>}
        </div>
      </div>
      <p className="mt-auto flex items-center justify-between gap-2 text-[12px] text-ink-secondary">
        {run ? <RunStatusBadge status={run.status} /> : <span>No runs</span>}
        <span title={formatDateTime(campaign.updated_at)}>{formatRelative(campaign.updated_at)}</span>
      </p>
    </TiltCard>
  );
}

export function MoreCampaigns({ campaigns, cards, latestRun, total, className }: { campaigns: DirectoryCampaign[]; cards: Map<string, TodayCampaign>; latestRun: Map<string, Run>; total: string; className?: string }) {
  return (
    <section aria-labelledby="campaigns" className={cn("min-w-0", className)}>
      <TileHead id="campaigns" title="More campaigns" meta={total} />
      <ol className="-mx-1 flex snap-x gap-4 overflow-x-auto px-1 pt-1 pb-4">
        {campaigns.map((c) => (
          <CampaignCard key={c.id} campaign={c} card={cards.get(c.id)} run={latestRun.get(c.id)} />
        ))}
      </ol>
    </section>
  );
}

/** The known shape of Today as clay dough while the directory loads. */
export function TodaySkeleton() {
  return (
    <div role="status" aria-label="Reading your brands and campaigns" className="grid gap-4 lg:grid-cols-12">
      <div className="dough h-[22rem] rounded-[18px] lg:col-span-7" />
      <div className="dough h-[22rem] rounded-[18px] lg:col-span-5" />
      <div className="dough h-56 rounded-[18px] lg:col-span-7" />
      <div className="dough h-56 rounded-[18px] lg:col-span-5" />
    </div>
  );
}
