"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * FilmStrip: a video's keyframes as a strip of clay frames with sprocket rails. Moving the pointer along the strip
 * scrubs the preview frame by frame (a playhead follows the pointer); leaving returns to the selected frame. Click or
 * Enter selects. Arrow keys move between frames and the preview follows focus.
 *
 * `media` is any node (usually `<ApiImage path={scene.keyframe_url} alt=… />`); the preview re-renders the active
 * frame's node, so cached images swap instantly.
 *
 *   <FilmStrip ariaLabel="Scenes of the Marathi film" frames={scenes.map((s) => ({ id: s.id, at: clock(s.start_ms), label: `Scene ${s.position + 1}`,
 *     media: <ApiImage path={s.keyframe_url} alt={`Scene ${s.position + 1}`} /> }))} selectedId={sel} onSelect={setSel} />
 */
export type FilmFrame = { id: string; media: ReactNode; label?: string; at?: string; caption?: ReactNode };

export type FilmStripProps = {
  frames: FilmFrame[];
  ariaLabel: string;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Called as the pointer or focus moves over frames (null when it leaves): drive an outside preview with it. */
  onActiveChange?: (id: string | null) => void;
  /** Show the large preview above the strip. */
  preview?: boolean;
  /** Classes for the preview frame (set its aspect ratio here, e.g. "aspect-[9/16] max-h-80"). */
  previewClassName?: string;
  className?: string;
};

export function FilmStrip({ frames, ariaLabel, selectedId, onSelect, onActiveChange, preview = true, previewClassName, className }: FilmStripProps) {
  const [hover, setHoverIndex] = useState<number | null>(null);
  const [head, setHead] = useState<number | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const setHover = (i: number | null) => {
    if (i === hover) return;
    setHoverIndex(i);
    onActiveChange?.(i === null ? null : (frames[i]?.id ?? null));
  };
  const selected = Math.max(0, frames.findIndex((f) => f.id === selectedId));
  const active = hover ?? selected;
  const frame = frames[active];
  if (!frame) return null;

  const scrub = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse") return;
    const r = e.currentTarget.getBoundingClientRect();
    const k = Math.max(0, Math.min(0.9999, (e.clientX - r.left) / r.width));
    setHover(Math.floor(k * frames.length));
    setHead(k * 100);
  };
  const key = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? frames.length - 1 : null;
    if (next === null || next < 0 || next >= frames.length) return;
    e.preventDefault();
    buttons.current[next]?.focus();
  };

  return (
    <div className={cn("space-y-3", className)}>
      {preview && (
        <figure className="relative">
          <div className={cn("relative overflow-hidden rounded-xl bg-surface-muted shadow-clay [&_img]:size-full", previewClassName ?? "aspect-video")}>
            {frame.media}
          </div>
          <figcaption className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12.5px]">
            {frame.at && <span className="font-mono text-[11.5px] text-ink-muted tabular-nums">{frame.at}</span>}
            {frame.label && <span className="font-medium text-ink">{frame.label}</span>}
            {frame.caption && <span className="text-ink-secondary">{frame.caption}</span>}
          </figcaption>
        </figure>
      )}
      <div
        role="group"
        aria-label={ariaLabel}
        onPointerMove={scrub}
        onPointerLeave={() => {
          setHover(null);
          setHead(null);
        }}
        className="relative overflow-x-clip rounded-xl bg-[#17181c] px-2 py-3.5 shadow-clay dark:bg-surface-muted"
      >
        {/* Sprocket rails: the strip reads as film at a glance. */}
        <span aria-hidden className="absolute inset-x-2 top-1 h-1.5 bg-[radial-gradient(circle,rgb(255_255_255/0.32)_1.5px,transparent_2px)] bg-size-[12px_6px] bg-repeat-x" />
        <span aria-hidden className="absolute inset-x-2 bottom-1 h-1.5 bg-[radial-gradient(circle,rgb(255_255_255/0.32)_1.5px,transparent_2px)] bg-size-[12px_6px] bg-repeat-x" />
        <ol className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${frames.length}, minmax(0, 1fr))` }}>
          {frames.map((f, i) => {
            const isSelected = i === selected && selectedId != null;
            return (
              <li key={f.id}>
                <button
                  ref={(el) => {
                    buttons.current[i] = el;
                  }}
                  type="button"
                  aria-pressed={onSelect ? isSelected : undefined}
                  aria-label={[f.label ?? `Frame ${i + 1}`, f.at].filter(Boolean).join(", ")}
                  onClick={() => onSelect?.(f.id)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  onKeyDown={(e) => key(e, i)}
                  className={cn(
                    "relative block aspect-4/5 w-full overflow-hidden rounded-[5px] bg-black/40 transition-[scale,opacity] duration-200 [&_img]:size-full [&_img]:object-cover",
                    i === active ? "z-10 scale-[1.06] opacity-100" : "opacity-70 hover:opacity-100",
                    isSelected && "ring-2 ring-pop ring-offset-2 ring-offset-[#17181c] dark:ring-offset-surface-muted",
                  )}
                >
                  {f.media}
                </button>
              </li>
            );
          })}
        </ol>
        {head !== null && (
          <span aria-hidden className="pointer-events-none absolute inset-y-1 right-2 left-2" style={{ transform: `translateX(${head}%)` }}>
            <span className="absolute inset-y-0 left-0 w-0.5 rounded-full bg-pop" />
          </span>
        )}
      </div>
    </div>
  );
}
