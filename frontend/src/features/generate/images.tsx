"use client";

import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { cn } from "@/lib/utils";

import type { GenerateAssetRef } from "./api";

/**
 * An asset image fetched with the API token. `contain` shows the whole frame; `cover` fills a tile. The file is fetched when
 * the frame is within about 300 px of the viewport (or at once with `eager`), so a long gallery or a strip of references does
 * not download every picture on arrival; object URLs are shared and kept by the asset cache, so they are never revoked here.
 */
export function AssetImage({
  asset,
  alt,
  className,
  fit = "contain",
  eager,
}: {
  asset: Pick<GenerateAssetRef, "asset_id" | "url"> | null | undefined;
  alt: string;
  className?: string;
  fit?: "contain" | "cover";
  eager?: boolean;
}) {
  const [near, setNear] = useState(() => Boolean(eager) || typeof IntersectionObserver === "undefined");
  const placeholder = useRef<HTMLDivElement>(null);
  const src = useAssetObjectUrl(near && asset ? { id: asset.asset_id, content_url: asset.url } : null);
  useEffect(() => {
    const element = placeholder.current;
    if (near || !element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element -- authenticated object URL, not optimizable
    <img src={src} alt={alt} loading={eager ? "eager" : "lazy"} draggable={false} className={cn("size-full select-none", fit === "cover" ? "object-cover" : "object-contain", className)} />
  ) : (
    <div ref={placeholder} className={cn("grid size-full place-items-center text-ink-muted", className)} role="img" aria-label={`${alt} (loading)`}>
      <LoaderCircle aria-hidden className="size-5 animate-spin" />
    </div>
  );
}

/**
 * Before and after on one frame: drag the edge, or focus it and use the arrow keys (Home and End jump to the ends). The
 * "before" picture is the left part. Both pictures keep their own proportions inside the frame.
 */
export function CompareSlider({
  before,
  after,
  beforeLabel,
  afterLabel,
  aspect,
}: {
  before: GenerateAssetRef;
  after: GenerateAssetRef;
  beforeLabel: string;
  afterLabel: string;
  aspect: number;
}) {
  const [split, setSplit] = useState(50);
  const frame = useRef<HTMLDivElement>(null);
  const place = (clientX: number) => {
    const box = frame.current?.getBoundingClientRect();
    if (box) setSplit(Math.min(100, Math.max(0, ((clientX - box.left) / box.width) * 100)));
  };
  return (
    <div
      ref={frame}
      className="relative mx-auto max-h-[70vh] w-full touch-pan-y overflow-hidden rounded-xl border border-border bg-surface-muted shadow-well"
      style={{ aspectRatio: String(aspect), "--gen-split": `${split}%` } as CSSProperties}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        place(e.clientX);
      }}
      onPointerMove={(e) => e.buttons === 1 && place(e.clientX)}
    >
      <AssetImage asset={after} alt={afterLabel} className="absolute inset-0" />
      <div className="gen-compare-top absolute inset-0">
        <AssetImage asset={before} alt={beforeLabel} className="absolute inset-0" />
      </div>
      <span className="pointer-events-none absolute top-2 left-2 rounded-sm bg-surface-raised/90 px-1.5 py-0.5 text-[11px] font-medium text-ink shadow-card">{beforeLabel}</span>
      <span className="pointer-events-none absolute top-2 right-2 rounded-sm bg-surface-raised/90 px-1.5 py-0.5 text-[11px] font-medium text-ink shadow-card">{afterLabel}</span>
      <div
        role="slider"
        tabIndex={0}
        aria-label={`Compare ${beforeLabel} with ${afterLabel}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(split)}
        aria-valuetext={`${Math.round(split)} percent of the frame shows ${beforeLabel}`}
        onKeyDown={(e) => {
          const next = e.key === "ArrowRight" ? split + 5 : e.key === "ArrowLeft" ? split - 5 : e.key === "Home" ? 0 : e.key === "End" ? 100 : null;
          if (next !== null) {
            e.preventDefault();
            setSplit(Math.min(100, Math.max(0, next)));
          }
        }}
        className="gen-compare-handle absolute inset-y-0 z-10 w-11 -translate-x-1/2 cursor-ew-resize outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <span aria-hidden className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-surface-raised shadow-card" />
        <span aria-hidden className="absolute top-1/2 left-1/2 grid size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface-raised text-ink shadow-raised">
          ‹›
        </span>
      </div>
    </div>
  );
}
