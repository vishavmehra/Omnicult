"use client";

import { LoaderCircle, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/features/assets/asset-uploader";

import { useBlob, useObjectUrl, type Creative } from "./api";

/**
 * Plays the original. The server streams the whole file (no HTTP Range), so nothing is seeked remotely: the file is
 * downloaded once, on request, and scene changes then jump inside that local copy.
 */
export function Player({ creative, startMs }: { creative: Creative; startMs: number }) {
  const asset = creative.asset;
  const [wanted, setWanted] = useState(false);
  const blob = useBlob(wanted ? asset.content_url : null);
  const src = useObjectUrl(blob.data);
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const seek = () => {
    if (ref.current && ref.current.readyState >= 1) ref.current.currentTime = startMs / 1000;
  };
  useEffect(seek, [startMs, src]);

  if (!wanted) {
    return (
      <div className="space-y-1.5">
        <Button variant="outline" size="sm" onClick={() => setWanted(true)}>
          <Play aria-hidden />
          Load the {asset.kind} to play it here ({formatBytes(asset.size_bytes)})
        </Button>
        <p className="type-meta">The whole file downloads first. Choosing a scene then jumps to its start.</p>
      </div>
    );
  }
  if (blob.isError) return <ErrorState error={blob.error} onRetry={() => void blob.refetch()} />;
  if (!src) {
    return (
      <p role="status" className="flex items-center gap-2 text-[13px] text-ink-secondary">
        <LoaderCircle aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />
        Downloading the {asset.kind}…
      </p>
    );
  }
  return asset.kind === "video" ? (
    <video ref={ref} src={src} controls playsInline preload="metadata" onLoadedMetadata={seek} className="mx-auto max-h-[28rem] w-auto max-w-full rounded-lg bg-black" />
  ) : (
    <audio ref={ref} src={src} controls preload="metadata" onLoadedMetadata={seek} className="w-full" />
  );
}
