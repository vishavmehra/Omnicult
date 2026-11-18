"use client";

import { Lock, Type } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";

import { cn } from "@/lib/utils";

import { useBlob, useObjectUrl } from "./api";

export type StageBox = {
  id: string;
  /** Normalised [x, y, width, height], each 0 to 1 of the frame. */
  bbox: number[];
  label: string;
  tone: "anchor" | "text" | "locked";
  active?: boolean;
};

export type Rect = [number, number, number, number];

const MAX_H = "min(36rem, 70dvh)";
const clamp = (n: number) => Math.min(1, Math.max(0, n));

const TONE: Record<StageBox["tone"], string> = {
  anchor: "border-white",
  text: "border-primary",
  locked: "border-dashed border-warning",
};

/**
 * A keyframe with boxes drawn on it. The frame keeps its own aspect ratio (a 9:16 video stays tall), so a normalised
 * bbox lands on the same pixels the backend uses. With `onDraw`, dragging on the frame reports a new box.
 */
export function FrameStage({
  path,
  aspect,
  boxes = [],
  onDraw,
  alt,
  empty,
}: {
  path: string | null | undefined;
  /** width / height of the frame. */
  aspect: number | null;
  boxes?: StageBox[];
  onDraw?: (rect: Rect) => void;
  alt: string;
  empty?: string;
}) {
  const blob = useBlob(path);
  const src = useObjectUrl(blob.data);
  const ratio = aspect && aspect > 0 ? aspect : 9 / 16;
  const stageRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  const style = { aspectRatio: String(ratio), width: `calc(${MAX_H} * ${ratio})`, maxWidth: "100%" };

  if (!path) {
    return (
      <div className="clay-well mx-auto grid place-items-center rounded-xl px-4 text-center text-[13px] text-ink-muted" style={{ ...style, minHeight: "10rem" }}>
        {empty ?? "No picture for this scene."}
      </div>
    );
  }

  const point = (e: PointerEvent) => {
    const r = stageRef.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) };
  };

  return (
    <div ref={stageRef} className="clay-well relative mx-auto overflow-hidden rounded-xl" style={style}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated blob, not optimisable by next/image
        <img src={src} alt={alt} className="absolute inset-0 size-full select-none" draggable={false} />
      ) : (
        <div role="status" className="absolute inset-0 grid place-items-center px-3 text-center text-[13px] text-ink-muted">
          {blob.isError ? "The picture could not be loaded." : "Loading the keyframe…"}
        </div>
      )}
      {boxes.map((b) => (
        <div
          key={b.id}
          className={cn("pointer-events-none absolute border-2 shadow-[0_0_0_1px_rgb(0_0_0/0.55)]", TONE[b.tone], b.active && "border-[3px]")}
          style={{ left: `${b.bbox[0] * 100}%`, top: `${b.bbox[1] * 100}%`, width: `${b.bbox[2] * 100}%`, height: `${b.bbox[3] * 100}%` }}
        >
          <span className="absolute top-0 left-0 inline-flex max-w-full items-center gap-1 truncate bg-canvas/90 px-1.5 py-px text-[11px] font-medium text-ink">
            {b.tone === "locked" ? <Lock aria-hidden className="size-3 shrink-0" /> : b.tone === "text" ? <Type aria-hidden className="size-3 shrink-0" /> : null}
            <span className="truncate">{b.label}</span>
          </span>
        </div>
      ))}
      {onDraw && (
        <div
          aria-hidden
          className="absolute inset-0 cursor-crosshair touch-none"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            const p = point(e);
            setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
          }}
          onPointerMove={(e) => drag && setDrag({ ...drag, ...(({ x, y }) => ({ x1: x, y1: y }))(point(e)) })}
          onPointerUp={() => {
            if (drag) {
              const x = Math.min(drag.x0, drag.x1);
              const y = Math.min(drag.y0, drag.y1);
              const w = Math.abs(drag.x1 - drag.x0);
              const h = Math.abs(drag.y1 - drag.y0);
              if (w > 0.03 && h > 0.02) onDraw([x, y, w, h]);
            }
            setDrag(null);
          }}
          onPointerCancel={() => setDrag(null)}
        >
          {drag && (
            <div
              className="absolute border-2 border-dashed border-white bg-white/10 shadow-[0_0_0_1px_rgb(0_0_0/0.55)]"
              style={{
                left: `${Math.min(drag.x0, drag.x1) * 100}%`,
                top: `${Math.min(drag.y0, drag.y1) * 100}%`,
                width: `${Math.abs(drag.x1 - drag.x0) * 100}%`,
                height: `${Math.abs(drag.y1 - drag.y0) * 100}%`,
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
