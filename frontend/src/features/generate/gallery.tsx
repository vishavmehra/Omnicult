"use client";

import { CircleX, Mic, Music2, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/states";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { GenerateItem, GenerateKind } from "./api";
import { PlayerAudio, useAudioPlayer } from "./audio";
import { AssetImage } from "./images";
import { Chip, mmss } from "./parts";

const FILTERS: { key: GenerateKind | "all"; label: string }[] = [
  { key: "all", label: "Everything" },
  { key: "image", label: "Images" },
  { key: "voice", label: "Voice-overs" },
  { key: "jingle", label: "Jingles" },
];

/** A picture tile keeps its own proportions between 4:5 and 16:9 and shows the whole creative; a sound tile is 4:3. */
const tileRatio = (item: GenerateItem) => (item.kind === "image" && item.image ? Math.min(16 / 9, Math.max(4 / 5, item.image.width / item.image.height)) : 4 / 3);

function Bars({ peaks, active }: { peaks: number[]; active: boolean }) {
  const bars = peaks.filter((_, i) => i % 2 === 0);
  return (
    <svg viewBox={`0 0 ${bars.length * 4} 40`} preserveAspectRatio="none" aria-hidden className="h-full w-full">
      {bars.map((p, i) => {
        const h = Math.max(3, (p / 100) * 34);
        return <rect key={i} x={i * 4} y={(40 - h) / 2} width={2.6} height={h} rx={1.3} className={cn("transition-colors", active ? "fill-primary" : "fill-border-strong")} />;
      })}
    </svg>
  );
}

/**
 * One finished run. A picture shows itself; a sound shows its loudness and plays when the pointer rests on it (and from the
 * play button, which is the keyboard route). A run that failed shows its error code, so a provider failure is never hidden.
 */
function Tile({ item, selected, onSelect }: { item: GenerateItem; selected: boolean; onSelect: () => void }) {
  const [armed, setArmed] = useState(false);
  const [hover, setHover] = useState(false);
  const rest = useRef(0);
  useEffect(() => () => window.clearTimeout(rest.current), []);
  const sound = item.kind !== "image" && item.asset;
  const player = useAudioPlayer(armed && sound ? item.asset : null, [], { live: false });
  const { preview, src } = player;
  useEffect(() => {
    // the file is fetched on the first hover, so the preview starts once it has arrived and the pointer is still there
    if (!hover || !src) return;
    preview(true);
    return () => preview(false);
  }, [hover, src, preview]);
  const peaks = item.voice?.peaks ?? item.jingle?.peaks ?? [];
  const failed = item.status === "failed" || !item.asset;
  const Icon = item.kind === "voice" ? Mic : Music2;
  return (
    <li className="gen-tile min-w-0">
      <div
        className={cn("relative overflow-hidden rounded-card border bg-surface shadow-raised", selected ? "border-primary ring-2 ring-primary/40" : "border-border")}
        onPointerEnter={(e) => {
          if (e.pointerType !== "mouse" || !sound) return;
          // the pointer has to rest on the tile for a moment: crossing it on the way elsewhere makes no sound and fetches no file
          window.clearTimeout(rest.current);
          rest.current = window.setTimeout(() => {
            setArmed(true);
            setHover(true);
          }, 250);
        }}
        onPointerLeave={() => {
          window.clearTimeout(rest.current);
          setHover(false);
        }}
      >
        <button type="button" onClick={onSelect} aria-pressed={selected} className="block w-full text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40">
          <div className="relative bg-surface-muted" style={{ aspectRatio: failed ? 4 / 3 : tileRatio(item) }}>
            {failed ? (
              <div className="grid size-full place-items-center p-3 text-center">
                <div className="space-y-1">
                  <CircleX aria-hidden className="mx-auto size-6 text-danger" />
                  <p className="text-[13px] font-medium text-ink">Did not finish</p>
                  <p className="type-meta">{item.error?.code ?? "No file"}</p>
                </div>
              </div>
            ) : item.kind === "image" ? (
              <AssetImage asset={item.asset} alt={item.title} fit="contain" />
            ) : (
              <div className="flex size-full flex-col justify-between p-3">
                <Icon aria-hidden className="size-5 text-ink-secondary" />
                <div className="h-14">
                  <Bars peaks={peaks} active={player.playing} />
                </div>
              </div>
            )}
            {!failed && sound && (
              <span className="type-meta absolute top-2 right-2 rounded-sm bg-surface-raised/90 px-1.5 py-0.5 tabular-nums text-ink shadow-card">
                {mmss(item.voice?.total_duration_ms ?? item.jingle?.duration_ms ?? 0)}
              </span>
            )}
          </div>
          <div className="space-y-0.5 px-3 py-2.5">
            <p className="truncate text-[13.5px] font-medium text-ink">{item.title}</p>
            <p className="type-meta">
              {formatRelative(item.created_at)}
              {item.mode === "demo" ? " · saved demonstration" : ""}
            </p>
          </div>
        </button>
        {sound && !failed && (
          <>
            <PlayerAudio bind={player.bind} src={player.src} />
            <button
              type="button"
              onClick={() => {
                setArmed(true);
                player.toggle();
              }}
              aria-label={`${player.playing && !player.previewing ? "Stop" : "Play"} ${item.title}`}
              className="absolute right-2 bottom-2 grid size-9 place-items-center rounded-full bg-primary text-primary-foreground shadow-clay outline-none focus-visible:ring-3 focus-visible:ring-ring/40 max-sm:size-11"
            >
              <Play aria-hidden className="size-3.5" />
            </button>
          </>
        )}
      </div>
    </li>
  );
}

/** Everything made for this campaign, newest first. */
export function Gallery({ items, selectedId, onSelect }: { items: GenerateItem[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const [filter, setFilter] = useState<GenerateKind | "all">("all");
  const shown = filter === "all" ? items : items.filter((i) => i.kind === filter);
  const count = (key: GenerateKind | "all") => (key === "all" ? items.length : items.filter((i) => i.kind === key).length);
  return (
    <section aria-labelledby="gen-gallery" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="gen-gallery" className="type-title text-[24px] text-ink">
          Gallery
        </h2>
        <div role="group" aria-label="Filter the gallery" className="flex flex-wrap gap-2">
          {FILTERS.map((f) => (
            <Chip key={f.key} pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label} <span className="type-meta tabular-nums">{count(f.key)}</span>
            </Chip>
          ))}
        </div>
      </div>
      {items.length === 0 ? (
        <EmptyState title="Nothing generated yet" description="Run a generator above. Each result lands here with the model, prompt version and cost that made it, ready to download or add to Studio." />
      ) : shown.length === 0 ? (
        <p className="text-[13.5px] text-ink-secondary">Nothing of this kind yet.</p>
      ) : (
        <ul className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((item) => (
            <Tile key={item.id} item={item} selected={item.id === selectedId} onSelect={() => onSelect(item.id)} />
          ))}
        </ul>
      )}
    </section>
  );
}
