"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import type { Digest } from "./logic";

/** Comment filters shared by the summary, the themes and the comment list (a null field is not applied). */
export type CommentFilters = { region: string | null; version: string | null; language: string | null; from: string | null; to: string | null };
export const NO_FILTERS: CommentFilters = { region: null, version: null, language: null, from: null, to: null };
export type ListOptions = { flag: "any" | "planted_claim" | "cultural_misstep" | null; sentiment: "positive" | "neutral" | "negative" | "mixed" | null; theme: string | null; sort: "likes" | "recent"; limit: number };

const comments = (id: string) => ["pulse-comments", id] as const;
const digests = (id: string) => ["pulse-digests", id] as const;
const path = (campaignId: string) => ({ path: { campaign_id: campaignId } });
/** A 409 means "not loaded yet" and does not get better by retrying. */
const noRetry = { retry: false } as const;

function scope(f: CommentFilters) {
  return { region: f.region ?? undefined, version: f.version ?? undefined, language: f.language ?? undefined, date_from: f.from ?? undefined, date_to: f.to ?? undefined };
}

// --- Comment Pulse -----------------------------------------------------------------------------------------------

export function useCommentStatus(campaignId: string) {
  return useQuery({
    queryKey: [...comments(campaignId), "status"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/comments/status", { params: path(campaignId) })),
    ...noRetry,
  });
}

export function useLoadComments(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/comments/sample", { params: path(campaignId) })),
    onSuccess: (status) => {
      queryClient.setQueryData([...comments(campaignId), "status"], status);
      void queryClient.invalidateQueries({ queryKey: comments(campaignId) });
    },
  });
}

export function useReadComments(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (force: boolean) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/comments/read", { params: path(campaignId), body: { force } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: comments(campaignId) }),
  });
}

export function useCommentSummary(campaignId: string, f: CommentFilters, enabled: boolean) {
  return useQuery({
    queryKey: [...comments(campaignId), "summary", f],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/comments/summary", { params: { ...path(campaignId), query: scope(f) } })),
    ...noRetry,
  });
}

export function useCommentThemes(campaignId: string, f: CommentFilters, enabled: boolean) {
  return useQuery({
    queryKey: [...comments(campaignId), "themes", f],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/comments/themes", { params: { ...path(campaignId), query: scope(f) } })),
    ...noRetry,
  });
}

export function useCommentList(campaignId: string, f: CommentFilters, o: ListOptions, enabled: boolean) {
  return useQuery({
    queryKey: [...comments(campaignId), "list", f, o],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/pulse/comments", {
          params: { ...path(campaignId), query: { ...scope(f), flag: o.flag ?? undefined, sentiment: o.sentiment ?? undefined, theme: o.theme ?? undefined, sort: o.sort, limit: o.limit } },
        }),
      ),
    ...noRetry,
  });
}

// --- Weekly Digest -------------------------------------------------------------------------------------------------

export function useDigests(campaignId: string) {
  return useQuery({
    queryKey: [...digests(campaignId), "list"],
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/digests", { params: path(campaignId) })),
  });
}

export function useDigest(campaignId: string, digestId: string | null) {
  return useQuery({
    queryKey: [...digests(campaignId), "one", digestId],
    enabled: Boolean(digestId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/pulse/digests/{digest_id}", { params: { path: { campaign_id: campaignId, digest_id: digestId! } } })),
  });
}

/** Generating is deterministic and synchronous: the response is the finished digest (an existing week comes back unchanged). */
export function useCreateDigest(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { week_of: string; regenerate: boolean }) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/digests", { params: path(campaignId), body })),
    onSuccess: ({ digest }) => {
      queryClient.setQueryData([...digests(campaignId), "one", digest.id], digest);
      return queryClient.invalidateQueries({ queryKey: [...digests(campaignId), "list"] });
    },
  });
}

/** The optional model summary of a stored digest (live projects only). */
export function useAddSummary(campaignId: string, digestId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/pulse/digests/{digest_id}/summary", { params: { path: { campaign_id: campaignId, digest_id: digestId } } })),
    onSuccess: (digest) => {
      queryClient.setQueryData([...digests(campaignId), "one", digest.id], digest);
      return queryClient.invalidateQueries({ queryKey: [...digests(campaignId), "list"] });
    },
  });
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type ExportFormat = "md" | "pdf";
export const EXPORT_LABEL: Record<ExportFormat, string> = { md: "Markdown", pdf: "PDF" };

/** Download a digest through the signed-in request. The server renders it (the same exporters as a Proof Report) and names the file. */
export async function downloadDigest(campaignId: string, digest: Pick<Digest, "id" | "content">, format: ExportFormat) {
  let response: Response | undefined;
  const blob = await unwrap(
    api
      .GET("/api/v1/campaigns/{campaign_id}/pulse/digests/{digest_id}/export", {
        params: { path: { campaign_id: campaignId, digest_id: digest.id }, query: { format } },
        parseAs: "blob",
      })
      .then((result) => {
        response = result.response;
        return result;
      }),
  );
  const named = /filename="([^"]+)"/.exec(response?.headers.get("content-disposition") ?? "")?.[1];
  saveBlob(blob as Blob, named ?? `omnicult-digest-${digest.content.week.label}.${format}`);
}
