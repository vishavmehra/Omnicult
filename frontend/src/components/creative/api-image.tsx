"use client";

import { useQuery } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";

import { getAccessToken } from "@/lib/auth/token";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

/**
 * ApiImage: an image the API serves behind auth (`/api/v1/assets/<id>/content`, a scene's `keyframe_url`, a creative's
 * `thumbnail_url`). Fetched once with the session token and kept as an object URL (shared cache key with
 * `useAssetObjectUrl`), shown as clay dough while it loads, faded in when it lands, and a quiet "image unavailable"
 * tile when the file cannot be read. Never use it for stock or placeholder art.
 *
 *   <ApiImage path={creative.thumbnail_url} alt="Maharashtra key visual" className="aspect-[4/5] w-full rounded-xl" />
 */
export function ApiImage({ path, alt, className, fit = "cover" }: { path: string | null | undefined; alt: string; className?: string; fit?: "cover" | "contain" }) {
  const q = useQuery({
    queryKey: ["asset-content", path],
    enabled: Boolean(path),
    staleTime: Infinity,
    retry: 1,
    queryFn: async () => {
      const token = await getAccessToken();
      const res = await fetch(`${env.apiBaseUrl}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(`Could not load the image (${res.status}).`);
      return URL.createObjectURL(await res.blob());
    },
  });
  if (q.isError || !path) {
    return (
      <span role="img" aria-label={`${alt} (image unavailable)`} className={cn("grid place-items-center bg-surface-muted text-ink-muted", className)}>
        <ImageOff aria-hidden className="size-5" />
      </span>
    );
  }
  if (!q.data) return <span role="img" aria-label={`${alt} (loading)`} className={cn("dough block", className)} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- authenticated object URL, not optimizable by next/image
    <img
      src={q.data}
      alt={alt}
      draggable={false}
      onLoad={(e) => e.currentTarget.setAttribute("data-loaded", "")}
      className={cn("opacity-0 transition-opacity duration-300 data-loaded:opacity-100", fit === "cover" ? "object-cover" : "object-contain", className)}
    />
  );
}
