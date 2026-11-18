"use client";

import { Download, ExternalLink, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented, SelectField } from "@/features/pulse/ui";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useMutation, useQueryClient } from "@tanstack/react-query";

type Youtube = NonNullable<components["schemas"]["CommentDatasetStatus"]["youtube"]>;
type Source = components["schemas"]["YoutubeSourceInfo"];
type FetchRequest = components["schemas"]["YoutubeFetchRequest"];
type Order = FetchRequest["order"];

const ORDER_LABEL: Record<Order, string> = { relevance: "Most relevant", time: "Newest" };

const path = (campaignId: string) => ({ path: { campaign_id: campaignId } });

/** Fetching or removing a video changes every Comment Pulse view, so all of the campaign's comment queries reload. */
function useRefreshComments(campaignId: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["pulse-comments", campaignId] });
}

function useFetchYoutube(campaignId: string) {
  const refresh = useRefreshComments(campaignId);
  return useMutation({
    mutationFn: (body: FetchRequest) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/comments/youtube", { params: path(campaignId), body })),
    onSuccess: refresh,
  });
}

function useRemoveYoutube(campaignId: string) {
  const refresh = useRefreshComments(campaignId);
  return useMutation({
    mutationFn: (sourceId: string) =>
      unwrap(api.DELETE("/api/v1/campaigns/{campaign_id}/pulse/comments/youtube/{source_id}", { params: { path: { campaign_id: campaignId, source_id: sourceId } } })),
    onSuccess: refresh,
  });
}

/**
 * Comment Pulse source (live projects): attach a public YouTube video to a campaign version and region. The server reads the
 * video's comments with its own API key and keeps their text, day, likes and replies, never who wrote them.
 */
export function YoutubeSourcePanel({ campaignId, youtube }: { campaignId: string; youtube: Youtube }) {
  const fetchVideo = useFetchYoutube(campaignId);
  const remove = useRemoveYoutube(campaignId);
  const videoId = useId();
  const [video, setVideo] = useState("");
  const [version, setVersion] = useState(youtube.versions[0] ?? "");
  const [region, setRegion] = useState(youtube.regions[0]?.code ?? "");
  const [order, setOrder] = useState<Order>("relevance");
  const [confirming, setConfirming] = useState<string | null>(null);
  const replaces = youtube.sources.find((s) => s.version_label === version && s.region_code === region);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!video.trim()) return;
    fetchVideo.mutate({ video: video.trim(), version_label: version, region_code: region, order }, { onSuccess: () => setVideo("") });
  }

  const done = fetchVideo.data;
  return (
    <section aria-labelledby="youtube-source" className="space-y-3">
      <h3 id="youtube-source" className="text-[15px] font-semibold text-ink">
        Comments from YouTube
      </h3>
      <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
        Paste a public YouTube video for a version and region. Up to {youtube.max_comments} of its comments are read from YouTube on the server. Only each comment&apos;s text, day,
        likes and reply count are kept, never who wrote it.
      </p>
      {youtube.sources.length > 0 && (
        <ul className="divide-y divide-border rounded-card border border-border bg-surface">
          {youtube.sources.map((s) => (
            <SourceRow
              key={s.id}
              source={s}
              busy={fetchVideo.isPending || remove.isPending}
              confirming={confirming === s.id}
              onRefresh={() => fetchVideo.mutate({ video: s.video_id, version_label: s.version_label, region_code: s.region_code, order: s.order })}
              onAskRemove={() => setConfirming(s.id)}
              onCancel={() => setConfirming(null)}
              onRemove={() => remove.mutate(s.id, { onSettled: () => setConfirming(null) })}
            />
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-x-4 gap-y-3 rounded-card border border-border bg-surface px-4 py-3">
        <div className="min-w-[15rem] flex-1 space-y-1">
          <label htmlFor={videoId} className="block text-[12px] font-medium text-ink-secondary">
            Video link or id
          </label>
          <Input id={videoId} value={video} onChange={(e) => setVideo(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" inputMode="url" autoComplete="off" spellCheck={false} />
        </div>
        <SelectField label="Version" className="w-52" value={version} onChange={setVersion} options={youtube.versions.map((v) => ({ value: v, label: v }))} />
        <SelectField
          label="Region"
          className="w-48"
          value={region}
          onChange={setRegion}
          options={youtube.regions.map((r) => ({ value: r.code, label: r.in_campaign ? `${r.name} (campaign market)` : r.name }))}
        />
        <div className="space-y-1">
          <p className="text-[12px] font-medium text-ink-secondary">Comments</p>
          <Segmented label="Comment order" value={order} onChange={setOrder} options={(["relevance", "time"] as const).map((o) => ({ value: o, label: ORDER_LABEL[o] }))} />
        </div>
        <Button type="submit" disabled={!video.trim() || fetchVideo.isPending}>
          {fetchVideo.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Download aria-hidden />}
          {fetchVideo.isPending ? "Fetching…" : replaces ? "Replace video" : "Fetch comments"}
        </Button>
        {replaces && <p className="basis-full text-[12.5px] text-ink-muted">This version and region already has a video. Fetching another replaces it and removes its comments.</p>}
      </form>
      {fetchVideo.error && <ErrorState error={fetchVideo.error} />}
      {remove.error && <ErrorState error={remove.error} />}
      {done && !fetchVideo.error && (
        <p role="status" className="text-[12.5px] text-ink-secondary">
          Fetched {done.fetched} comments from {done.source.video_title ?? done.source.video_id}: {done.added} new, {done.updated} already stored
          {done.source.truncated ? `. The page cap stopped at ${done.source.pages_fetched} pages; the video has more comments` : ""}.
        </p>
      )}
    </section>
  );
}

function SourceRow({
  source: s,
  busy,
  confirming,
  onRefresh,
  onAskRemove,
  onCancel,
  onRemove,
}: {
  source: Source;
  busy: boolean;
  confirming: boolean;
  onRefresh: () => void;
  onAskRemove: () => void;
  onCancel: () => void;
  onRemove: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
      <div className="min-w-0 space-y-0.5 text-[13.5px]">
        <a href={s.video_url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 font-medium text-ink hover:underline">
          <span className="truncate">{s.video_title ?? s.video_id}</span>
          <ExternalLink aria-hidden className="size-3.5 shrink-0 text-ink-muted" />
          <span className="sr-only">(opens YouTube)</span>
        </a>
        <p className="type-meta">
          {s.version_label} · {s.region_name} · {s.comments} comments · {ORDER_LABEL[s.order]} · fetched {formatDateTime(s.fetched_at)}
        </p>
        {s.truncated && <p className="type-meta">The page cap stopped at {s.pages_fetched} pages; the video has more comments.</p>}
        {s.next_fetch_at && <p className="type-meta">Can be fetched again after {formatDateTime(s.next_fetch_at)}.</p>}
      </div>
      <div className={cn("flex items-center gap-2")}>
        {confirming ? (
          <>
            <Button variant="destructive" size="sm" onClick={onRemove} disabled={busy}>
              <Trash2 aria-hidden />
              Remove {s.comments} comments
            </Button>
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Keep
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={busy}>
              <RefreshCw aria-hidden />
              Fetch again
            </Button>
            <Button variant="ghost" size="sm" onClick={onAskRemove} disabled={busy} className="text-ink-secondary">
              Remove
            </Button>
          </>
        )}
      </div>
    </li>
  );
}
