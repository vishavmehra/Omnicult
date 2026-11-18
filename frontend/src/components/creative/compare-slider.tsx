"use client";

import { MoveHorizontal } from "lucide-react";
import { useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * CompareSlider: before on the left, after on the right, a clay handle between them. Drag anywhere, click to jump, or
 * focus the handle and use the arrow keys (Shift for bigger steps, Home and End for the ends). The wipe is two opposing
 * translateX layers, so dragging never repaints the content or touches layout.
 *
 * Works for images and for text: both layers share one grid cell, so the taller one sets the height. Give text layers an
 * opaque background (`layerClassName="bg-mat"`) so the covered side does not show through.
 *
 *   <CompareSlider before={<ApiImage path={original} alt="Original" />} after={<ApiImage path={remake} alt="Remake" />}
 *     beforeLabel="Original" afterLabel="Tamil Nadu" />
 */
export type CompareSliderProps = {
  before: ReactNode;
  after: ReactNode;
  beforeLabel: string;
  afterLabel: string;
  /** Starting handle position, 0 to 100 (share of the width showing `before`). */
  initial?: number;
  className?: string;
  layerClassName?: string;
};

export function CompareSlider({ before, after, beforeLabel, afterLabel, initial = 50, className, layerClassName }: CompareSliderProps) {
  const [pos, setPos] = useState(initial);
  const [dragging, setDragging] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const fromPointer = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return pos;
    return Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100));
  };
  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    setPos(fromPointer(e.clientX));
  };
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragging) setPos(fromPointer(e.clientX));
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 10 : 5;
    const next =
      e.key === "ArrowLeft" || e.key === "ArrowDown" ? pos - step : e.key === "ArrowRight" || e.key === "ArrowUp" ? pos + step : e.key === "Home" ? 0 : e.key === "End" ? 100 : null;
    if (next === null) return;
    e.preventDefault();
    setPos(Math.max(0, Math.min(100, next)));
  };

  return (
    <div
      ref={box}
      className={cn("relative grid touch-pan-y overflow-hidden rounded-xl select-none", dragging ? "cursor-grabbing" : "cursor-ew-resize", className)}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={() => setDragging(false)}
      onPointerCancel={() => setDragging(false)}
    >
      <div className={cn("[grid-area:1/1]", layerClassName)}>{before}</div>
      <div className="overflow-hidden [grid-area:1/1]" style={{ transform: `translateX(${pos}%)` }}>
        <div className={cn("h-full", layerClassName)} style={{ transform: `translateX(${-pos}%)` }}>
          {after}
        </div>
      </div>

      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-2.5 left-2.5 rounded-md bg-surface-raised/90 px-2 py-0.5 text-[11.5px] font-medium text-ink shadow-clay transition-opacity duration-200",
          pos < 18 && "opacity-0",
        )}
      >
        {beforeLabel}
      </span>
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-2.5 right-2.5 rounded-md bg-surface-raised/90 px-2 py-0.5 text-[11.5px] font-medium text-ink shadow-clay transition-opacity duration-200",
          pos > 82 && "opacity-0",
        )}
      >
        {afterLabel}
      </span>

      {/* The rule and the handle ride one full-width layer moved by transform, so dragging never touches layout. */}
      <div className="pointer-events-none absolute inset-0" style={{ transform: `translateX(${pos}%)` }}>
        <div aria-hidden className="absolute inset-y-0 left-0 w-0.5 -translate-x-1/2 bg-surface-raised shadow-clay" />
        <div
          role="slider"
          tabIndex={0}
          aria-label={`Compare ${beforeLabel} with ${afterLabel}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pos)}
          aria-valuetext={`${Math.round(pos)} percent ${beforeLabel}, ${100 - Math.round(pos)} percent ${afterLabel}`}
          onKeyDown={key}
          className="pointer-events-auto absolute top-1/2 left-0 grid size-10 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface-raised text-ink shadow-clay transition-[scale] duration-200 hover:scale-105 active:scale-95"
        >
          <MoveHorizontal aria-hidden className="size-4" />
        </div>
      </div>
    </div>
  );
}
